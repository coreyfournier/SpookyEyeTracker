"""Camera pixel -> world ground position, and world point -> eye pan/tilt.

Simple pinhole model built from the camera's position, heading, pitch, roll and
horizontal FOV. Good enough for a first guess; calibration refines the pose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MIN_FACE_H, MAX_FACE_H = 0.5, 2.3   # plausible eye-level heights (m)


@dataclass
class Location:
    x: float
    y: float
    face_h: float | None      # measured eye-level height, None if it couldn't be measured
    ray_o: np.ndarray         # camera position
    ray_d: np.ndarray         # unit ray through the face pixel (for two-camera triangulation)


def triangulate(o1, d1, o2, d2, max_gap: float = 0.6, min_angle_deg: float = 8.0):
    """Midpoint of the closest approach of two rays, or None if they don't nearly meet."""
    b = float(d1 @ d2)
    if abs(b) > math.cos(math.radians(min_angle_deg)):
        return None  # rays nearly parallel - depth is unreliable
    w0 = o1 - o2
    d, e = float(d1 @ w0), float(d2 @ w0)
    den = 1 - b * b
    s, t = (b * e - d) / den, (e - b * d) / den
    if s <= 0 or t <= 0:
        return None
    p1, p2 = o1 + s * d1, o2 + t * d2
    if np.linalg.norm(p1 - p2) > max_gap:
        return None
    p = (p1 + p2) / 2
    return p if MIN_FACE_H <= p[2] <= MAX_FACE_H else None


def _basis(heading_deg: float, pitch_deg: float, roll_deg: float = 0.0):
    """Forward/right/up unit vectors for a heading (0=+Y, +90=+X) and pitch (+up)."""
    h, p, r = map(math.radians, (heading_deg, pitch_deg, roll_deg))
    fwd = np.array([math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), math.sin(p)])
    right = np.array([math.cos(h), -math.sin(h), 0.0])
    up = np.cross(right, fwd)
    if r:
        right, up = (right * math.cos(r) + up * math.sin(r),
                     -right * math.sin(r) + up * math.cos(r))
    return fwd, right, up


class CameraModel:
    def __init__(self, cam: dict, width: int, height: int):
        self.pos = np.array(cam["position"], dtype=float)
        self.fwd, self.right, self.up = _basis(cam["heading"], cam["pitch"], cam.get("roll", 0.0))
        self.w, self.h = width, height
        self.f = (width / 2) / math.tan(math.radians(cam["hfov"]) / 2)

    def ray(self, u: float, v: float) -> np.ndarray:
        x = (u - self.w / 2) / self.f
        y = (v - self.h / 2) / self.f
        d = self.fwd + x * self.right - y * self.up
        return d / np.linalg.norm(d)

    def _hit_plane(self, u: float, v: float, z: float, max_range: float = 60.0):
        d = self.ray(u, v)
        if d[2] >= -1e-3 or self.pos[2] <= z:
            return None
        t = (z - self.pos[2]) / d[2]
        return None if t > max_range else self.pos + t * d

    def feet_visible(self, box) -> bool:
        return box[3] < self.h - 4

    def locate(self, box, face_px, default_face_h: float) -> Location:
        """Ground position and eye-level height of a person.

        box = (x1, y1, x2, y2); face_px = pixel of their eyes (see camera.face_pixel).
        """
        x1, y1, x2, y2 = box
        cx = (x1 + x2) / 2
        d_face = self.ray(*face_px)
        if self.feet_visible(box):
            g = self._hit_plane(cx, y2, 0.0)
            if g is not None:
                # Follow the face ray out to the person's horizontal distance -> its height there.
                horiz = math.hypot(g[0] - self.pos[0], g[1] - self.pos[1])
                dxy = math.hypot(d_face[0], d_face[1])
                face_h = self.pos[2] + d_face[2] * horiz / dxy if dxy > 1e-3 else None
                if face_h is not None and not MIN_FACE_H <= face_h <= MAX_FACE_H:
                    face_h = None
                return Location(g[0], g[1], face_h, self.pos, d_face)
        # Feet cut off: assume a typical eye level and intersect the face ray with that plane.
        p = self._hit_plane(*face_px, default_face_h)
        if p is None:
            # Last resort: distance from apparent size (assumes ~1.7 m tall).
            dist = 1.7 * self.f / max(y2 - y1, 1.0)
            p = self.pos + d_face * dist
        return Location(p[0], p[1], None, self.pos, d_face)

    def project(self, world_xyz) -> tuple[float, float] | None:
        """World point -> pixel (for drawing), None if behind the camera."""
        d = np.asarray(world_xyz, dtype=float) - self.pos
        z = d @ self.fwd
        if z <= 0.1:
            return None
        return (self.w / 2 + self.f * (d @ self.right) / z, self.h / 2 - self.f * (d @ self.up) / z)


def servo_us(axis: dict, deg: float) -> int:
    """Same mapping the firmware uses (eye_config ServoAxis), for predictions on the PC."""
    deg = min(max(deg, axis["min"]), axis["max"])
    return int(min(max(round(axis["center"] + deg * axis["us_per_deg"]), 500), 2500))


def eye_angles(eye: dict, target_xy, look_height: float) -> tuple[float, float]:
    """Pan/tilt in the eye's own frame (+pan right, +tilt up), degrees."""
    ex, ey, ez = eye["position"]
    dx, dy, dz = target_xy[0] - ex, target_xy[1] - ey, look_height - ez
    bearing = math.degrees(math.atan2(dx, dy))
    pan = (bearing - eye["heading"] + 180) % 360 - 180
    tilt = math.degrees(math.atan2(dz, math.hypot(dx, dy))) - eye.get("pitch", 0.0)
    return pan, tilt
