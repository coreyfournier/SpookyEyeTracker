"""Calibrate-by-pointing: stand in the yard, jog the eye until it looks at you, capture.

Each sample pairs where the cameras think you are (x, y, eye-level height) with the
servo microseconds that actually point the eye at you. Fitting
    us = center + us_per_deg * angle
per axis absorbs servo offsets, linkage ratio, and errors in the camera/eye poses.
Samples are kept in calibration.json (next to config.yaml) so they survive restarts and can be refit
after editing the eye's position.
"""
from __future__ import annotations

import json
import math
import threading

import numpy as np

from .geometry import eye_angles, servo_us

SAMPLES_NAME = "calibration.json"         # stored next to config.yaml
MIN_SPREAD = {"pan": 8.0, "tilt": 4.0}     # deg of spread needed to fit scale, else offset only
SCALE_LIMITS = (5.0, 80.0)                 # plausible |us_per_deg|


class Calibrator:
    def __init__(self, store, world):
        self.store = store
        self.world = world
        self._lock = threading.Lock()
        self.samples_file = store.data_dir / SAMPLES_NAME
        try:
            self._samples = json.loads(self.samples_file.read_text())
        except (OSError, ValueError):
            self._samples = {}

    def _save(self):
        self.samples_file.write_text(json.dumps(self._samples, indent=1))

    def target(self, eye: dict):
        """The person to calibrate against: the one closest to the eye."""
        people = self.world.people(max_age=0.5)
        if not people:
            return None
        ex, ey = eye["position"][:2]
        return min(people, key=lambda p: math.hypot(p.x - ex, p.y - ey))

    def _angles(self, eye, s) -> tuple[float, float]:
        return eye_angles(eye, (s["x"], s["y"]), s["face_h"] or self.store.section("world")["look_height"])

    def target_info(self, eye: dict) -> dict | None:
        p = self.target(eye)
        if p is None:
            return None
        s = {"x": p.x, "y": p.y, "face_h": p.face_h}
        pan, tilt = self._angles(eye, s)
        servos = eye["firmware"]["servos"]
        return {"id": p.id, "x": round(p.x, 2), "y": round(p.y, 2),
                "face_h": round(p.face_h, 2) if p.face_h else None, "height_src": p.height_src,
                "dist": round(math.hypot(p.x - eye["position"][0], p.y - eye["position"][1]), 1),
                "pan": round(pan, 1), "tilt": round(tilt, 1),
                "pred_pan_us": servo_us(servos["pan"], pan), "pred_tilt_us": servo_us(servos["tilt"], tilt)}

    def samples(self, eye: dict) -> list[dict]:
        with self._lock:
            out = [dict(s) for s in self._samples.get(eye["id"], [])]
        for s in out:
            s["pan"], s["tilt"] = (round(a, 1) for a in self._angles(eye, s))
        return out

    def capture(self, eye: dict, pan_us: int, tilt_us: int) -> dict:
        p = self.target(eye)
        if p is None:
            raise ValueError("nobody detected - step into view of a camera")
        s = {"x": round(p.x, 3), "y": round(p.y, 3), "face_h": round(p.face_h, 3) if p.face_h else None,
             "pan_us": int(pan_us), "tilt_us": int(tilt_us)}
        with self._lock:
            self._samples.setdefault(eye["id"], []).append(s)
            self._save()
        return s

    def delete(self, eye_id: str, index: int):
        with self._lock:
            lst = self._samples.get(eye_id, [])
            if 0 <= index < len(lst):
                lst.pop(index)
                self._save()

    def clear(self, eye_id: str):
        with self._lock:
            self._samples[eye_id] = []
            self._save()

    def fit(self, eye: dict) -> dict:
        samples = self.samples(eye)
        servos = eye["firmware"]["servos"]
        return {axis: self._fit_axis([s[axis] for s in samples], [s[f"{axis}_us"] for s in samples],
                                     servos[axis]["us_per_deg"], MIN_SPREAD[axis]) for axis in ("pan", "tilt")}

    @staticmethod
    def _fit_axis(deg, us, current_scale, min_spread) -> dict | None:
        if not deg:
            return None
        x, y = np.array(deg, float), np.array(us, float)
        mode, scale = "offset", current_scale
        if len(x) >= 2 and np.ptp(x) >= min_spread:
            k, _ = np.polyfit(x, y, 1)
            if SCALE_LIMITS[0] <= abs(k) <= SCALE_LIMITS[1]:
                mode, scale = "offset+scale", float(k)
            else:
                mode = "offset (scale fit implausible - check the samples)"
        center = float(np.mean(y - scale * x))
        resid = y - (center + scale * x)
        rms_us = float(np.sqrt(np.mean(resid ** 2)))
        return {"center": round(center), "us_per_deg": round(scale, 2), "mode": mode, "n": len(x),
                "rms_us": round(rms_us, 1), "rms_deg": round(rms_us / abs(scale), 2)}

    def apply(self, eye_id: str) -> dict:
        """Write the fit into the eye's servo config and save config.yaml. Returns the updated eye."""
        eye = self.store.eye(eye_id)
        fit = self.fit(eye)
        if not any(fit.values()):
            raise ValueError("no samples captured yet")
        for axis, f in fit.items():
            if f:
                eye["firmware"]["servos"][axis]["center"] = f["center"]
                eye["firmware"]["servos"][axis]["us_per_deg"] = f["us_per_deg"]
        self.store.replace_item("eyes", eye, save=True)
        return eye
