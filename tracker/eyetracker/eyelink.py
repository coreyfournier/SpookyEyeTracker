"""UDP link to the ESP32 eyes (one socket for all eyes, addressed by static IP)."""
from __future__ import annotations

import json
import logging
import socket
import threading
import time

from .config import ConfigStore, firmware_version

log = logging.getLogger(__name__)

PING_INTERVAL = 2.0
OFFLINE_AFTER = 6.0


class EyeLink:
    def __init__(self, store: ConfigStore):
        self.store = store
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(0.5)
        self._status: dict[str, dict] = {}       # eye id -> last status packet + meta
        self._acks: dict[str, threading.Event] = {}
        self._acked_ver: dict[str, int] = {}
        self._lock = threading.Lock()
        self.last_look: dict[str, dict] = {}

    def start(self):
        threading.Thread(target=self._recv_loop, name="eyelink-rx", daemon=True).start()
        threading.Thread(target=self._ping_loop, name="eyelink-ping", daemon=True).start()

    # ---------- sending ----------
    def _addr_to_eye(self, ip: str) -> str | None:
        for e in self.store.section("eyes") or []:
            if e["ip"] == ip:
                return e["id"]
        return None

    def send(self, eye: dict, msg: dict):
        try:
            self.sock.sendto(json.dumps(msg, separators=(",", ":")).encode(), (eye["ip"], eye.get("port", 4210)))
        except OSError as exc:
            log.debug("send to %s failed: %s", eye["id"], exc)

    def look(self, eye: dict, target: bool, pan: float = 0, tilt: float = 0, new: bool = False):
        msg = {"t": "look", "tgt": int(target), "pan": round(pan, 2), "tilt": round(tilt, 2), "new": int(new)}
        self.last_look[eye["id"]] = msg
        self.send(eye, msg)

    def manual(self, eye: dict, pan=0.0, tilt=0.0, lid=1.0, raw=None, hold_s=15.0):
        self.send(eye, {"t": "manual", "pan": pan, "tilt": tilt, "lid": lid, "raw": raw or [0, 0, 0, 0],
                        "hold_s": hold_s})

    def release(self, eye: dict):
        self.send(eye, {"t": "release"})

    def push_config(self, eye: dict, retries: int = 4, timeout: float = 0.6) -> bool:
        """Send the eye's firmware block and wait for an ack with the matching version."""
        fw = eye["firmware"]
        ver = firmware_version(fw)
        msg = {"t": "cfg", "ver": ver, **fw}
        ev = threading.Event()
        with self._lock:
            self._acks[eye["id"]] = ev
        for _ in range(retries):
            self.send(eye, msg)
            if ev.wait(timeout) and self._acked_ver.get(eye["id"]) == ver:
                log.info("%s: config %08x acknowledged", eye["id"], ver)
                return True
            ev.clear()
        log.warning("%s: config push not acknowledged", eye["id"])
        return False

    # ---------- receiving ----------
    def _recv_loop(self):
        while True:
            try:
                data, (ip, _port) = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                # Windows raises ConnectionResetError on ICMP port-unreachable; ignore
                continue
            eye_id = self._addr_to_eye(ip)
            if eye_id is None:
                log.info("packet from unknown eye at %s - add it to config.yaml", ip)
                continue
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            if msg.get("t") == "status":
                with self._lock:
                    self._status[eye_id] = {**msg, "seen": time.time()}
            elif msg.get("t") == "ack":
                with self._lock:
                    self._acked_ver[eye_id] = msg.get("ver")
                    ev = self._acks.get(eye_id)
                if ev:
                    ev.set()

    def _ping_loop(self):
        while True:
            for eye in self.store.section("eyes") or []:
                if eye.get("enabled", True):
                    self.send(eye, {"t": "ping"})
            time.sleep(PING_INTERVAL)

    def status(self, eye: dict) -> dict:
        with self._lock:
            st = dict(self._status.get(eye["id"], {}))
        online = bool(st) and time.time() - st["seen"] < OFFLINE_AFTER
        want = firmware_version(eye["firmware"])
        return {"online": online, "state": st.get("state"),
                "activity": st.get("act") or st.get("state"),   # track/hold/wander/sleep/... (older firmware: state)
                "pan": st.get("pan"), "tilt": st.get("tilt"),
                "rssi": st.get("rssi"), "uptime": st.get("up"),
                "fw": {"version": st.get("fw"), "built": st.get("built"), "board": st.get("board"),
                       "ota": bool(st.get("ota"))},
                "config_in_sync": online and st.get("ver") == want,
                "last_look": self.last_look.get(eye["id"])}
