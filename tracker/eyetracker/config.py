"""Loads/saves config.yaml and resolves camera credentials from the project .env."""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import zlib
from pathlib import Path
from urllib.parse import quote

import yaml
from dotenv import load_dotenv

TRACKER_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = TRACKER_DIR.parent
BUNDLED_CONFIG = TRACKER_DIR / "config.default.yaml"   # committed template
# Live config: $EYETRACKER_CONFIG (Docker: /config/config.yaml), else tracker-data/ (git-ignored).
DEFAULT_CONFIG = Path(os.environ.get("EYETRACKER_CONFIG", PROJECT_DIR / "tracker-data" / "config.yaml"))
MAX_CAMERAS = 2
# How a camera's video is reached: Hikvision's RTSP channels, any ONVIF camera (asked for its RTSP
# address), any stream URL, or a USB camera on this PC
CAMERA_TYPES = ("hikvision", "onvif", "rtsp", "usb")
UNIT_SYSTEMS = ("metric", "imperial")   # display only - the config itself is always metres

load_dotenv(PROJECT_DIR / ".env")


class ConfigError(ValueError):
    pass


def firmware_version(fw: dict) -> int:
    """Stable 32-bit hash of an eye's firmware block, used to detect config drift."""
    blob = json.dumps(fw, sort_keys=True, separators=(",", ":")).encode()
    return zlib.crc32(blob) & 0x7FFFFFFF


def _check_ids(items, kind, errors):
    ids = [i.get("id") for i in items]
    if any(not i for i in ids):
        errors.append(f"every {kind} needs an id")
    dupes = {i for i in ids if i and ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate {kind} id(s): {', '.join(sorted(dupes))}")


def validate(cfg: dict) -> list[str]:
    """Problems with a config dict, empty if it's usable."""
    errors = []
    cameras = cfg.get("cameras") or []
    eyes = cfg.get("eyes") or []
    if len(cameras) > MAX_CAMERAS:
        errors.append(f"at most {MAX_CAMERAS} cameras are supported (found {len(cameras)})")
    _check_ids(cameras, "camera", errors)
    _check_ids(eyes, "eye", errors)
    for c in cameras:
        kind = c.get("type", "hikvision")
        if kind not in CAMERA_TYPES:
            errors.append(f"camera {c.get('id')}: type must be one of {', '.join(CAMERA_TYPES)} (got {kind!r})")
        elif kind in ("hikvision", "onvif") and not (c.get("ip") or c.get("ip_env")):
            errors.append(f"camera {c.get('id')}: set ip or ip_env")
        elif kind == "rtsp" and not str(c.get("url", "")).startswith(("rtsp://", "rtsps://", "http://", "https://")):
            errors.append(f"camera {c.get('id')}: url must be a stream address (rtsp://...)")
        elif kind == "usb" and str(c.get("device", "")).strip() == "":
            errors.append(f"camera {c.get('id')}: set device (0 = the first USB camera)")
        for key in ("position", "heading", "pitch", "hfov"):
            if key not in c:
                errors.append(f"camera {c.get('id')}: missing {key}")
    for e in eyes:
        for key in ("ip", "position", "heading", "firmware"):
            if key not in e:
                errors.append(f"eye {e.get('id')}: missing {key}")
    units = (cfg.get("ui") or {}).get("units", "metric")
    if units not in UNIT_SYSTEMS:
        errors.append(f"ui.units must be one of {', '.join(UNIT_SYSTEMS)} (got {units!r})")
    for key in ("world", "detection", "tracking", "director", "web"):
        if key not in cfg:
            errors.append(f"missing section: {key}")
    return errors


def _upgrade_eye(eye: dict) -> None:
    """Fill in settings added since an older config was written."""
    iris = (((eye.get("firmware") or {}).get("behaviors") or {}).get("iris"))
    if isinstance(iris, dict) and "brightness" in iris and "sclera_brightness" not in iris:
        # brightness used to cover all 7 LEDs; it now only sets the centre (iris) LED.
        # Insert the ring's own setting right after it, at the same level.
        items = list(iris.items())
        i = [k for k, _ in items].index("brightness") + 1
        items.insert(i, ("sclera_brightness", iris["brightness"]))
        iris.clear()
        iris.update(items)


def _upgrade_camera(cam: dict) -> None:
    """Cameras from before camera types were all Hikvision: say so, right after the id."""
    if "type" not in cam:
        items = list(cam.items())
        keys = [k for k, _ in items]
        items.insert(keys.index("id") + 1 if "id" in keys else 0, ("type", "hikvision"))
        cam.clear()
        cam.update(items)


def ensure_config(path: Path) -> Path:
    """Copy the bundled default config to `path` on first run (e.g. an empty Docker volume)."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUNDLED_CONFIG, path)
    return path


class ConfigStore:
    """Thread-safe holder for the live config. Readers get deep copies."""

    def __init__(self, path: Path = DEFAULT_CONFIG):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._read()
        self.revision = 0  # bumps on every change so workers can refresh cached geometry

    @property
    def data_dir(self) -> Path:
        """Where runtime data (calibration samples) lives - next to config.yaml."""
        return self.path.parent

    def _read(self) -> dict:
        with open(self.path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("cameras", [])
        data.setdefault("eyes", [])
        for e in data["eyes"]:
            _upgrade_eye(e)
        for c in data["cameras"]:
            _upgrade_camera(c)
        errors = validate(data)
        if errors:
            raise ConfigError(f"{self.path}: " + "; ".join(errors))
        return data

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def section(self, key: str):
        with self._lock:
            return copy.deepcopy(self._data.get(key))

    def eye(self, eye_id: str) -> dict | None:
        with self._lock:
            for e in self._data.get("eyes", []):
                if e["id"] == eye_id:
                    return copy.deepcopy(e)
        return None

    def camera(self, cam_id: str) -> dict | None:
        with self._lock:
            for c in self._data.get("cameras", []):
                if c["id"] == cam_id:
                    return copy.deepcopy(c)
        return None

    def update(self, data: dict, save: bool) -> None:
        errors = validate(data)
        if errors:
            raise ConfigError("; ".join(errors))
        with self._lock:
            self._data = copy.deepcopy(data)
            self.revision += 1
            if save:
                tmp = self.path.with_suffix(".yaml.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    yaml.safe_dump(self._data, f, sort_keys=False, default_flow_style=None, width=120)
                os.replace(tmp, self.path)

    def replace_item(self, key: str, item: dict, save: bool) -> None:
        data = self.get()
        items = data.setdefault(key, [])
        for i, existing in enumerate(items):
            if existing["id"] == item["id"]:
                items[i] = item
                break
        else:
            items.append(item)
        self.update(data, save)

    def remove_item(self, key: str, item_id: str, save: bool) -> bool:
        data = self.get()
        items = data.setdefault(key, [])
        kept = [i for i in items if i["id"] != item_id]
        if len(kept) == len(items):
            return False
        data[key] = kept
        self.update(data, save)
        return True


def camera_ip(cam: dict) -> str:
    """Camera IP: from the env variable named by ip_env if it is set, else the literal ip."""
    env = cam.get("ip_env")
    return (os.environ.get(env) if env else None) or cam.get("ip", "")


def camera_login(cam: dict, creds: dict) -> tuple[str, str]:
    """Username and password from the .env variables named by the camera (username_env /
    password_env, e.g. a separate ONVIF user), else by the shared credentials section."""
    user_env = cam.get("username_env") or creds["username_env"]
    pw_env = cam.get("password_env") or creds["password_env"]
    return os.environ.get(user_env, ""), os.environ.get(pw_env, "")


def rtsp_url(cam: dict, creds: dict) -> str:
    """Hikvision's RTSP address for a camera's channel (101 = main stream, 102 = sub stream)."""
    user, pw = camera_login(cam, creds)
    return (f"rtsp://{quote(user, safe='')}:{quote(pw, safe='')}@{camera_ip(cam)}:{cam.get('rtsp_port', 554)}"
            f"/Streaming/Channels/{cam.get('channel', 101)}")


def custom_url(cam: dict, creds: dict) -> str:
    """A camera's own stream URL, with {user}, {password} and {ip} filled in from the .env."""
    user, pw = camera_login(cam, creds)
    return (cam.get("url", "").replace("{user}", quote(user, safe="")).replace("{password}", quote(pw, safe=""))
            .replace("{ip}", camera_ip(cam)))


def usb_device(cam: dict) -> int | str:
    """USB camera: an index (0 = the first camera) or a device path such as /dev/video2."""
    d = cam.get("device", 0)
    return int(d) if isinstance(d, (int, float)) or str(d).strip().isdigit() else str(d)


def redact(url: str, *secrets: str) -> str:
    """Hide passwords in a stream URL before it's logged."""
    for pw in (os.environ.get("CAMERA_PASSWORD", ""), *secrets):
        if pw:
            url = url.replace(quote(pw, safe=""), "***").replace(pw, "***")
    return url
