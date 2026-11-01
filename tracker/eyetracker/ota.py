"""Over-the-air firmware upload to an eye (see firmware/src/ota.cpp).

Standard library only, so firmware/scripts/ota_upload.py can use it from PlatformIO's
own Python as well as the tracker.
"""
from __future__ import annotations

import base64
import os
import urllib.error
import urllib.request
import uuid

# PlatformIO board ids the firmware supports; each image embeds its own as FW_BOARD.
KNOWN_BOARDS = ("heltec_wifi_kit_32_v2", "featheresp32")
ESP_IMAGE_MAGIC = 0xE9


class OtaError(Exception):
    pass


def detect_board(image: bytes) -> str:
    """Which board an image was built for. Raises OtaError if it isn't eye firmware."""
    if not image or image[0] != ESP_IMAGE_MAGIC:
        raise OtaError("not an ESP32 firmware image (.bin from firmware/.pio/build/<eye>/firmware.bin)")
    found = [b for b in KNOWN_BOARDS if b.encode() + b"\0" in image]
    if len(found) != 1:
        raise OtaError("can't tell which board this firmware is for - is it from this project?")
    return found[0]


def ota_password() -> str:
    pw = os.environ.get("EYE_OTA_PASSWORD", "")
    if not pw:
        raise OtaError("EYE_OTA_PASSWORD is not set (add it to .env)")
    return pw


def upload(ip: str, image: bytes, password: str, port: int = 80, timeout: float = 90.0) -> str:
    """Send an image to the eye at `ip`. Returns the eye's reply; raises OtaError on failure."""
    board = detect_board(image)
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"firmware\"; filename=\"firmware.bin\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + image + f"\r\n--{boundary}--\r\n".encode()
    auth = base64.b64encode(f"eye:{password}".encode()).decode()
    req = urllib.request.Request(f"http://{ip}:{port}/update?board={board}", data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Basic {auth}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace").strip()
        if exc.code == 401:
            raise OtaError("the eye rejected the OTA password") from exc
        if exc.code == 404:
            raise OtaError("this eye has no update endpoint - flash it over USB once with OTA firmware") from exc
        raise OtaError(f"eye returned {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise OtaError(f"couldn't reach the eye's update endpoint at {ip}: {exc}") from exc
