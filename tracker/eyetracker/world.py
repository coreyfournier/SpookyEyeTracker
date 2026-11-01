"""Fuses per-camera detections into a single list of people in world coordinates."""
from __future__ import annotations

import itertools
import math
import threading
import time
from dataclasses import dataclass, field

from .geometry import triangulate

RAY_MAX_AGE = 0.3   # s - face rays from two cameras must be this close in time to triangulate


@dataclass
class Person:
    id: int
    x: float
    y: float
    first_seen: float
    last_seen: float
    cams: dict = field(default_factory=dict)   # cam_id -> last time seen by that camera
    face_h: float | None = None                # smoothed eye-level height (m)
    height_src: str = ""                       # "stereo" | "mono" | "" (unmeasured)
    rays: dict = field(default_factory=dict)   # cam_id -> (origin, dir, time)

    def to_dict(self, now: float) -> dict:
        return {"id": self.id, "x": round(self.x, 2), "y": round(self.y, 2),
                "face_h": round(self.face_h, 2) if self.face_h else None, "height_src": self.height_src,
                "age": round(now - self.first_seen, 1), "cams": sorted(self.cams)}


class World:
    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()
        self._people: dict[int, Person] = {}
        self._links: dict[tuple[str, int], int] = {}   # (cam, local track id) -> person id
        self._ids = itertools.count(1)

    def update(self, cam_id: str, dets, now: float, enabled: bool = True):
        cfg = self.store.section("tracking")
        merge, alpha = cfg["merge_distance"], cfg["smoothing"]
        with self._lock:
            self._expire(now, cfg["max_age"])
            if not enabled:
                return
            claimed: set[int] = set()
            for d in dets:
                pid = self._links.get((cam_id, d.local_id)) if d.local_id >= 0 else None
                person = self._people.get(pid) if pid is not None else None
                if person is None or pid in claimed:
                    person = self._nearest(d.world, merge, claimed)
                if person is None:
                    person = Person(next(self._ids), d.world[0], d.world[1], now, now)
                    self._people[person.id] = person
                else:
                    # snappier when only one camera sees them, averaged when several do
                    a = alpha if len(person.cams) <= 1 else alpha * 0.6
                    person.x += (d.world[0] - person.x) * a
                    person.y += (d.world[1] - person.y) * a
                    person.last_seen = now
                person.cams[cam_id] = now
                claimed.add(person.id)
                if d.local_id >= 0:
                    self._links[(cam_id, d.local_id)] = person.id
                d.world_id = person.id
                if cfg.get("measure_height", True):
                    self._update_height(person, cam_id, d, now, cfg.get("height_smoothing", 0.15), alpha)
            self._merge_close(merge * 0.5)

    def _update_height(self, person: Person, cam_id: str, d, now: float, k: float, alpha: float):
        if d.ray is not None:
            person.rays[cam_id] = (d.ray[0], d.ray[1], now)
        # Two cameras seeing the same face recently -> triangulate (no flat-ground assumption).
        for other, (o, v, t) in person.rays.items():
            if other == cam_id or now - t > RAY_MAX_AGE or d.ray is None:
                continue
            p = triangulate(d.ray[0], d.ray[1], o, v)
            if p is not None:
                person.x += (p[0] - person.x) * alpha * 0.5
                person.y += (p[1] - person.y) * alpha * 0.5
                self._blend_height(person, float(p[2]), min(1.0, k * 2), "stereo")
                return
        if d.face_h is not None:
            # A recent stereo fix is better than a single camera - only nudge it gently.
            self._blend_height(person, d.face_h, k * (0.3 if person.height_src == "stereo" else 1.0), "mono",
                               keep_src=person.height_src == "stereo")

    @staticmethod
    def _blend_height(person: Person, h: float, k: float, src: str, keep_src: bool = False):
        person.face_h = h if person.face_h is None else person.face_h + (h - person.face_h) * k
        if not keep_src:
            person.height_src = src

    def _nearest(self, xy, max_dist, exclude):
        best, best_d = None, max_dist
        for p in self._people.values():
            if p.id in exclude:
                continue
            dist = math.hypot(p.x - xy[0], p.y - xy[1])
            if dist < best_d:
                best, best_d = p, dist
        return best

    def _merge_close(self, dist):
        people = sorted(self._people.values(), key=lambda p: p.first_seen)
        for i, a in enumerate(people):
            for b in people[i + 1:]:
                if a.id in self._people and b.id in self._people and \
                        math.hypot(a.x - b.x, a.y - b.y) < dist and not (set(a.cams) & set(b.cams)):
                    # same person seen by two cameras - keep the older id
                    a.cams.update(b.cams)
                    a.rays.update(b.rays)
                    if a.face_h is None:
                        a.face_h, a.height_src = b.face_h, b.height_src
                    a.last_seen = max(a.last_seen, b.last_seen)
                    del self._people[b.id]
                    for k, v in self._links.items():
                        if v == b.id:
                            self._links[k] = a.id

    def _expire(self, now, max_age):
        for p in list(self._people.values()):
            p.cams = {c: t for c, t in p.cams.items() if now - t < max_age}
            if now - p.last_seen > max_age:
                del self._people[p.id]
        self._links = {k: v for k, v in self._links.items() if v in self._people}

    def people(self, max_age: float | None = None) -> list[Person]:
        now = time.time()
        with self._lock:
            return [Person(p.id, p.x, p.y, p.first_seen, p.last_seen, dict(p.cams), p.face_h, p.height_src)
                    for p in self._people.values() if max_age is None or now - p.last_seen <= max_age]
