"""Decides which person each eye looks at and streams pan/tilt to the eyes.

Detection (cameras -> World) knows nothing about eyes; the director knows
nothing about cameras. Adding eyes means adding entries to config.yaml, and
assignment strategies are plain functions registered in STRATEGIES.
"""
from __future__ import annotations

import logging
import math
import threading
import time

from .geometry import eye_angles

log = logging.getLogger(__name__)

AUTO_PUSH_INTERVAL = 10.0


def _candidates(eye, people, look_height, max_pan):
    out = []
    for p in people:
        pan, tilt = eye_angles(eye, (p.x, p.y), p.face_h or look_height)
        if abs(pan) <= max_pan:
            dist = math.hypot(p.x - eye["position"][0], p.y - eye["position"][1])
            out.append((dist, p, pan, tilt))
    return sorted(out, key=lambda c: c[0])


def _keep_or_switch(current_id, cands, margin):
    """Closest candidate, but stick with the current person unless someone is `margin` m closer."""
    if not cands:
        return None
    best = cands[0]
    cur = next((c for c in cands if c[1].id == current_id), None)
    if cur is not None and cur[0] - best[0] < margin:
        return cur
    return best


def strategy_closest(eyes, people, current, cfg):
    d = cfg["director"]
    look_h = cfg["world"]["look_height"]
    return {e["id"]: _keep_or_switch(current.get(e["id"]), _candidates(e, people, look_h, d["max_pan"]),
                                     d["switch_margin"]) for e in eyes}


def strategy_spread(eyes, people, current, cfg):
    """Like closest, but once a person is taken, other eyes prefer someone else."""
    d = cfg["director"]
    look_h = cfg["world"]["look_height"]
    taken, out = set(), {}
    for e in eyes:
        cands = _candidates(e, people, look_h, d["max_pan"])
        free = [c for c in cands if c[1].id not in taken] or cands
        pick = _keep_or_switch(current.get(e["id"]), free, d["switch_margin"])
        out[e["id"]] = pick
        if pick:
            taken.add(pick[1].id)
    return out


STRATEGIES = {"closest": strategy_closest, "spread": strategy_spread}


class Director:
    def __init__(self, store, world, link):
        self.store = store
        self.world = world
        self.link = link
        self.current: dict[str, int | None] = {}            # eye id -> person id
        self.overrides: dict[str, tuple[float, float, float]] = {}  # eye id -> (x, y, until)
        self.assignments: dict[str, dict] = {}
        self._last_push: dict[str, float] = {}

    def start(self):
        threading.Thread(target=self._loop, name="director", daemon=True).start()

    def look_at(self, eye_id: str, x: float, y: float, seconds: float = 5.0):
        """Point an eye at a world spot through the normal geometry (calibration aid)."""
        self.overrides[eye_id] = (x, y, time.time() + seconds)

    def _loop(self):
        while True:
            cfg = self.store.get()
            period = 1.0 / cfg["director"].get("rate_hz", 20)
            try:
                self._tick(cfg)
            except Exception:  # keep streaming even if one tick goes wrong
                log.exception("director tick failed")
            time.sleep(period)

    def _tick(self, cfg):
        now = time.time()
        eyes = [e for e in cfg["eyes"] if e.get("enabled", True)]
        people = self.world.people(max_age=0.5)
        strategy = STRATEGIES.get(cfg["director"]["strategy"], strategy_closest)
        picks = strategy(eyes, people, self.current, cfg)

        for eye in eyes:
            eid = eye["id"]
            ov = self.overrides.get(eid)
            if ov and ov[2] > now:
                pan, tilt = eye_angles(eye, ov[:2], cfg["world"]["look_height"])
                self.link.look(eye, True, pan, tilt)
                self.assignments[eid] = {"person": None, "override": [ov[0], ov[1]],
                                         "pan": round(pan, 1), "tilt": round(tilt, 1)}
                continue
            pick = picks.get(eid)
            if pick is None:
                self.current[eid] = None
                self.link.look(eye, False)
                self.assignments[eid] = {"person": None}
            else:
                dist, person, pan, tilt = pick
                new = self.current.get(eid) != person.id
                self.current[eid] = person.id
                self.link.look(eye, True, pan, tilt, new=new)
                self.assignments[eid] = {"person": person.id, "pan": round(pan, 1), "tilt": round(tilt, 1),
                                         "dist": round(dist, 1)}
            if cfg["director"].get("auto_push", True):
                self._auto_push(eye, now)

    def _auto_push(self, eye, now):
        """Re-push config to an eye that is online but out of sync (e.g. after it rebooted)."""
        st = self.link.status(eye)
        if st["online"] and not st["config_in_sync"] and now - self._last_push.get(eye["id"], 0) > AUTO_PUSH_INTERVAL:
            self._last_push[eye["id"]] = now
            threading.Thread(target=self.link.push_config, args=(eye,), daemon=True).start()
