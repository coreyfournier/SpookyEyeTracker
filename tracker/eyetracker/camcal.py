"""Camera calibration wizard: walk to a few spots, the tracker solves each camera's pose.

The phone page (/camcal) tells you where to go. At each spot the wizard waits for you to
stand still, records ~2 s of what every camera sees (the pixel of your eyes, and of your
feet when they're in frame), then asks you to move on. Your eye-level height is known (you
enter it), so each camera sighting is a ray that must pass through (x, y, eye height), and
your feet must be at (x, y, 0). Solving for every camera's position, heading, pitch, roll
and field of view - plus where each spot was - makes the cameras agree with each other and
with your real height. The first spot can be pinned to a measured position, which ties the
cameras to the eyes; without it the old poses (as soft priors) keep the frame in place.

Nothing changes until you Apply. The previous poses are kept so Apply can be undone.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import deque

import numpy as np

from .geometry import CameraModel

log = logging.getLogger(__name__)

STATE_NAME = "camera_calibration.json"   # stored next to config.yaml
EYE_BELOW_TOP = 0.11                     # m from the top of the head down to the eyes

# (key, title, what to tell the person)
STEPS = [
    ("center", "Center spot", "Stand on the center spot, face the house, arms by your sides, and stand still."),
    ("left", "Left", "Walk about 3 metres to your left, keep facing the house, and stand still."),
    ("right", "Right", "Now walk about 6 metres to your right, past the center spot, and stand still."),
    ("street", "Toward the street", "Go back to the center, then walk about 3 metres toward the street. Stand still."),
    ("house", "Toward the house", "Walk to a spot about 2 metres in front of the center spot, toward the house. "
                                  "Stand still."),
    ("pick", "Your pick", "Last one: pick a spot you haven't stood on, somewhere people usually walk past. "
                          "Stand still."),
]
EXTRA_STEP = ("extra", "Extra spot", "Walk to a new spot both cameras can see and stand still.")

SEEN_WINDOW = 0.6      # s - a camera "sees you" if it had exactly one person this recently
STILL_WINDOW = 1.2     # s of steady sightings needed before recording starts
STILL_TOL = 0.015      # fraction of image width the eyes/feet may wobble while "still"
RECORD_S = 2.0         # s recorded per spot
MOVE_TOL = 0.06        # fraction of image width you must move before the next spot
MIN_FRAMES = 4         # sightings a camera needs during a recording to count

# Soft priors on the current pose: how far the solver may move each value (1 sigma).
PRIOR_SIGMA = {"x": 1.5, "y": 1.5, "z": 0.75, "heading": 25.0, "pitch": 15.0, "roll": 5.0, "hfov": 20.0}
POSE_KEYS = ("x", "y", "z", "heading", "pitch", "roll", "hfov")
HFOV_RANGE = (30.0, 150.0)
FACE_SIGMA_DEG, FEET_SIGMA_DEG = 0.6, 0.9   # how well we trust a sighting


# ---------------------------------------------------------------- solver (pure functions)

def _pose(cam: dict) -> list[float]:
    x, y, z = cam["position"]
    return [x, y, z, cam["heading"], cam["pitch"], cam.get("roll", 0.0), cam["hfov"]]


def _with_pose(cam: dict, p) -> dict:
    out = dict(cam)
    out["position"] = [float(p[0]), float(p[1]), float(p[2])]
    out["heading"], out["pitch"], out["roll"] = float(p[3]), float(p[4]), float(p[5])
    out["hfov"] = float(min(max(p[6], HFOV_RANGE[0]), HFOV_RANGE[1]))
    return out


def _sightings(spots, cam_ids):
    """(spot index, cam index, sighting) for every camera that recorded a spot."""
    return [(si, ci, s["obs"][cid]) for si, s in enumerate(spots) for ci, cid in enumerate(cam_ids)
            if cid in s["obs"]]


def locate_spot(model: CameraModel, ob: dict, eye_h: float):
    """Where one camera thinks you stood: (x, y, measured eye height or None)."""
    loc = model.locate(ob["box"], ob["face"], eye_h)
    return loc.x, loc.y, loc.face_h


def spot_estimates(cams: list[dict], spots: list[dict], eye_h: float) -> list[dict]:
    """Per spot: each camera's own (x, y, eye height) - what disagreement looks like."""
    out = []
    for s in spots:
        per = {}
        for cam in cams:
            ob = s["obs"].get(cam["id"])
            if ob:
                model = CameraModel(cam, *ob["size"])
                x, y, h = locate_spot(model, ob, eye_h)
                per[cam["id"]] = {"x": round(float(x), 2), "y": round(float(y), 2),
                                  "eye_h": round(float(h), 2) if h is not None else None}
        out.append(per)
    return out


def quality(cams: list[dict], spots: list[dict], eye_h: float) -> dict:
    """How far apart the cameras put you, and how wrong your measured height is."""
    gaps, height_errs = [], []
    for per in spot_estimates(cams, spots, eye_h):
        pts = list(per.values())
        if len(pts) >= 2:
            gaps.append(math.hypot(pts[0]["x"] - pts[1]["x"], pts[0]["y"] - pts[1]["y"]))
        height_errs += [abs(p["eye_h"] - eye_h) for p in pts if p["eye_h"] is not None]
    return {"camera_gap_m": round(float(np.mean(gaps)), 2) if gaps else None,
            "height_err_m": round(float(np.mean(height_errs)), 2) if height_errs else None,
            "spots_both": len(gaps)}


def _initial_spots(cams, spots, eye_h, anchor):
    xy = []
    for i, per in enumerate(spot_estimates(cams, spots, eye_h)):
        if i == 0 and anchor is not None:
            xy.append(list(anchor))
        elif per:
            xy.append([float(np.mean([p["x"] for p in per.values()])), float(np.mean([p["y"] for p in per.values()]))])
        else:
            xy.append([0.0, 5.0])
    return xy


def solve(cams: list[dict], spots: list[dict], eye_h: float, anchor=None, iters: int = 200) -> dict:
    """Least-squares fit of every camera's pose and every spot's position.

    cams: camera config dicts (their current poses are the starting point and soft prior).
    spots: [{"obs": {cam_id: {"face": [u, v], "box": [x1, y1, x2, y2], "size": [w, h]}}}].
    anchor: (x, y) of spots[0] if it was measured, else None.
    """
    cam_ids = [c["id"] for c in cams]
    seen = _sightings(spots, cam_ids)
    if not seen:
        raise ValueError("no spots recorded")
    prior = np.array([_pose(c) for c in cams], float)
    sig = np.array([PRIOR_SIGMA[k] for k in POSE_KEYS])
    xy0 = np.array(_initial_spots(cams, spots, eye_h, anchor), float)
    free = [i for i in range(len(spots)) if not (i == 0 and anchor is not None)]
    nc = len(cams) * len(POSE_KEYS)

    def unpack(v):
        poses = v[:nc].reshape(len(cams), len(POSE_KEYS))
        xy = xy0.copy()
        xy[free] = v[nc:].reshape(-1, 2)
        return poses, xy

    def residuals(v):
        poses, xy = unpack(v)
        r = list(((poses - prior) / sig).ravel())
        posed = [_with_pose(c, p) for c, p in zip(cams, poses)]
        return np.array(r + [e / s for e, s in _reprojection(posed, seen, xy, eye_h)])

    v = np.concatenate([prior.ravel(), xy0[free].ravel()])
    v = _levenberg_marquardt(residuals, v, iters)
    poses, xy = unpack(v)
    new_cams = [_with_pose(c, p) for c, p in zip(cams, poses)]
    errs = [e for e, _ in _reprojection(new_cams, seen, xy, eye_h)]
    return {"cameras": new_cams, "spots_xy": [[round(float(a), 2), round(float(b), 2)] for a, b in xy],
            "rms_deg": round(float(np.sqrt(np.mean(np.square(errs)))), 2),
            "before": quality(cams, spots, eye_h), "after": quality(new_cams, spots, eye_h)}


def _reprojection(cams, seen, xy, eye_h):
    """(error in degrees, sigma) for each image coordinate of each sighting."""
    out, models = [], {}
    for si, ci, ob in seen:
        key = (ci, tuple(ob["size"]))
        if key not in models:
            models[key] = CameraModel(cams[ci], *ob["size"])
        m = models[key]
        x, y = xy[si]
        pts = [((x, y, eye_h), ob["face"], FACE_SIGMA_DEG)]
        if m.feet_visible(ob["box"]):
            pts.append(((x, y, 0.0), ((ob["box"][0] + ob["box"][2]) / 2, ob["box"][3]), FEET_SIGMA_DEG))
        for world, px, sigma in pts:
            p = m.project(world)
            if p is None:   # behind the camera - push hard back toward the view
                out += [(30.0 * sigma, sigma)] * 2
            else:
                to_deg = math.degrees(1 / m.f)
                out += [((p[0] - px[0]) * to_deg, sigma), ((p[1] - px[1]) * to_deg, sigma)]
    return out


def _levenberg_marquardt(fun, v, iters):
    r = fun(v)
    cost, lam = float(r @ r), 1e-2
    for _ in range(iters):
        jac = np.empty((len(r), len(v)))
        for j in range(len(v)):
            dv = np.zeros_like(v)
            dv[j] = 1e-4
            jac[:, j] = (fun(v + dv) - r) / 1e-4
        a, g = jac.T @ jac, jac.T @ r
        while True:
            step = np.linalg.solve(a + lam * (np.diag(np.diag(a)) + 1e-9 * np.eye(len(v))), -g)
            r_new = fun(v + step)
            new_cost = float(r_new @ r_new)
            if new_cost < cost:
                v, r, lam = v + step, r_new, max(lam / 3, 1e-7)
                break
            lam *= 4
            if lam > 1e8:
                return v
        if cost - new_cost < 1e-9 * max(cost, 1.0) or np.max(np.abs(step)) < 1e-6:
            return v
        cost = new_cost
    return v


# ---------------------------------------------------------------- wizard

class CameraCalibration:
    """Guides one person through the spots and records what each camera sees.

    feed() takes each camera's detections; tick() advances the step state machine. Both are
    driven by a poll thread when running for real (start_polling), or directly by tests.
    """

    def __init__(self, store, cameras=None):
        self.store = store
        self.cameras = cameras
        self._lock = threading.Lock()
        self._buf: dict[str, deque] = {}       # cam -> (t, face, box, size) with exactly one person
        self._crowd: dict[str, float] = {}     # cam -> last time it saw more than one person
        self._seq: dict[str, int] = {}
        saved = self._load()
        self.backup = saved.get("backup")      # camera poses before the last Apply
        self._reset_session()

    # ---------- persistence ----------
    @property
    def _path(self):
        return self.store.data_dir / STATE_NAME

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        data = {"eye_height": self.eye_h, "anchor": self.anchor, "spots": self.spots, "backup": self.backup}
        try:
            self._path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("couldn't save %s: %s", self._path, exc)

    # ---------- session ----------
    def _reset_session(self):
        self.phase = "idle"            # idle | running | review | solved
        self.steps = list(STEPS)
        self.index = 0
        self.sub = "settle"            # settle | record | move
        self.rec_start = 0.0
        self.last_capture: dict = {}   # cam -> (face, box) at the last capture
        self.spots: list[dict] = []
        self.eye_h = 1.55
        self.anchor = None
        self.result = None
        self.message = ""

    def start(self, height: float, anchor=None):
        if not 1.0 <= height <= 2.3:
            raise ValueError("height should be in metres, between 1.0 and 2.3")
        with self._lock:
            self._reset_session()
            self.eye_h = round(height - EYE_BELOW_TOP, 3)
            self.anchor = [float(anchor[0]), float(anchor[1])] if anchor else None
            self.phase = "running"
            self._buf.clear()
            self._crowd.clear()

    def cancel(self):
        with self._lock:
            self._reset_session()

    def skip(self):
        with self._lock:
            if self.phase == "running":
                self._next_step()

    def redo(self):
        """Throw away the last recorded spot and do it again."""
        with self._lock:
            if self.spots:
                self.spots.pop()
                self.index = self.spots[-1]["step"] + 1 if self.spots else 0
                self.index = min(self.index, len(self.steps) - 1)
            self.phase, self.sub, self.result, self.last_capture = "running", "settle", None, {}
            self._save()

    def more(self):
        """Add another spot after the planned ones."""
        with self._lock:
            self.steps.append(EXTRA_STEP)
            self.index = len(self.steps) - 1
            self.phase, self.sub, self.result = "running", "move" if self.last_capture else "settle", None

    def _next_step(self):
        self.index += 1
        self.sub = "move" if self.last_capture else "settle"
        if self.index >= len(self.steps):
            self.index = len(self.steps) - 1
            self.phase = "review"

    # ---------- observations ----------
    def feed(self, cam_id: str, dets, size, now: float):
        """One processed frame from a camera. Only frames with exactly one person are used."""
        with self._lock:
            if self.phase != "running":
                return
            if len(dets) > 1:
                self._crowd[cam_id] = now
            elif len(dets) == 1:
                d = dets[0]
                self._buf.setdefault(cam_id, deque(maxlen=200)).append(
                    (now, tuple(d.face_px), tuple(d.box), tuple(size)))

    def _recent(self, cam_id, since):
        return [o for o in self._buf.get(cam_id, ()) if o[0] >= since]

    def _seeing(self, now):
        return [c for c, b in self._buf.items() if b and now - b[-1][0] <= SEEN_WINDOW]

    def _still(self, cams, now, window):
        if not cams:
            return False
        for c in cams:
            obs = self._recent(c, now - window)
            if len(obs) < MIN_FRAMES or obs[0][0] > now - window * 0.8:
                return False
            w = obs[-1][3][0]
            face = np.array([o[1] for o in obs])
            feet = np.array([[(o[2][0] + o[2][2]) / 2, o[2][3]] for o in obs])
            if max(np.ptp(face, axis=0).max(), np.ptp(feet, axis=0).max()) > STILL_TOL * w:
                return False
        return True

    def _moved(self, cams, now):
        """Have you walked away from the last captured spot?"""
        if not self.last_capture:
            return True
        common = [c for c in cams if c in self.last_capture]
        if not common:
            return True   # a different set of cameras sees you now
        for c in common:
            face, box = self.last_capture[c]
            obs = self._recent(c, now - SEEN_WINDOW)
            w = obs[-1][3][0]
            if abs(obs[-1][1][0] - face[0]) > MOVE_TOL * w or abs(obs[-1][2][3] - box[3]) > MOVE_TOL * w:
                return True
        return False

    def tick(self, now: float | None = None):
        now = time.time() if now is None else now
        with self._lock:
            if self.phase != "running":
                return
            cams = self._seeing(now)
            crowded = [c for c, t in self._crowd.items() if now - t <= SEEN_WINDOW]
            if crowded:
                self.message = f"Someone else is in view of {', '.join(crowded)} - wait for them to leave."
                self.sub = "move" if self.sub == "move" else "settle"
                return
            if not cams:
                self.message = "I can't see you. Step into view of a camera."
                if self.sub == "record":
                    self.sub = "settle"
                return
            if self.sub == "move":
                if self._moved(cams, now):
                    self.sub = "settle"
                else:
                    self.message = "Head to the next spot."
                    return
            if self.sub == "settle":
                if self._still(cams, now, STILL_WINDOW):
                    self.sub, self.rec_start = "record", now
                    self.message = "Recording - hold still."
                else:
                    self.message = "Stand still when you get there."
                return
            # recording
            if not self._still(cams, now, STILL_WINDOW):
                self.sub = "settle"
                self.message = "You moved - hold still."
                return
            if now - self.rec_start >= RECORD_S:
                self._capture(now)

    def _capture(self, now):
        obs = {}
        for c in list(self._buf):
            rec = self._recent(c, self.rec_start)
            if len(rec) >= MIN_FRAMES:
                obs[c] = {"face": [round(float(v), 1) for v in np.median([o[1] for o in rec], axis=0)],
                          "box": [round(float(v), 1) for v in np.median([o[2] for o in rec], axis=0)],
                          "size": list(rec[-1][3])}
        if not obs:
            self.sub, self.message = "settle", "Lost you while recording - stand still in view."
            return
        key, title, _ = self.steps[self.index]
        self.spots.append({"step": self.index, "key": key, "title": title, "obs": obs})
        self.last_capture = {c: (tuple(o["face"]), tuple(o["box"])) for c, o in obs.items()}
        self.message = f"Got it ({len(obs)} camera{'s' if len(obs) > 1 else ''})."
        self._save()
        self._next_step()

    # ---------- solve / apply ----------
    def _cams(self):
        used = {c for s in self.spots for c in s["obs"]}
        return [c for c in self.store.section("cameras") or [] if c["id"] in used]

    def solve(self) -> dict:
        with self._lock:
            if len(self.spots) < 3:
                raise ValueError("record at least 3 spots first")
            cams, spots, eye_h, anchor = self._cams(), list(self.spots), self.eye_h, self.anchor
        if anchor is not None and self.spots[0]["key"] != "center":
            anchor = None   # the center spot was skipped, so nothing is pinned
        result = solve(cams, spots, eye_h, anchor)
        result["spots_seen_by"] = [sorted(s["obs"]) for s in spots]
        with self._lock:
            self.result, self.phase = result, "solved"
        return result

    def apply(self) -> list[dict]:
        with self._lock:
            if not self.result:
                raise ValueError("solve first")
            new = self.result["cameras"]
        backup = []
        for cam in new:
            current = self.store.camera(cam["id"])
            if current is None:
                continue
            backup.append({k: current[k] for k in ("id", "position", "heading", "pitch", "roll", "hfov") if k in current})
            current.update({"position": [round(v, 2) for v in cam["position"]], "heading": round(cam["heading"], 1),
                            "pitch": round(cam["pitch"], 1), "roll": round(cam["roll"], 1),
                            "hfov": round(cam["hfov"], 1)})
            self.store.replace_item("cameras", current, save=True)
        with self._lock:
            self.backup = backup
            self.phase = "idle"
            self._save()
        return backup

    def undo(self):
        """Restore the camera poses from before the last Apply."""
        with self._lock:
            backup = self.backup
        if not backup:
            raise ValueError("nothing to undo")
        for old in backup:
            current = self.store.camera(old["id"])
            if current is not None:
                current.update(old)
                self.store.replace_item("cameras", current, save=True)
        with self._lock:
            self.backup = None
            self._save()

    # ---------- status ----------
    def status(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            key, title, text = self.steps[self.index]
            seeing = self._seeing(now) if self.phase == "running" else []
            cams = [c["id"] for c in self.store.section("cameras") or [] if c.get("enabled", True)]
            progress = min(1.0, (now - self.rec_start) / RECORD_S) if self.sub == "record" else 0.0
            return {
                "phase": self.phase, "sub": self.sub, "message": self.message, "progress": round(progress, 2),
                "step": {"index": self.index, "total": len(self.steps), "key": key, "title": title, "text": text},
                "seeing": {c: c in seeing for c in cams},
                "spots": [{"title": s["title"], "cams": sorted(s["obs"])} for s in self.spots],
                "eye_height": self.eye_h, "anchor": self.anchor,
                "result": self.result, "can_undo": bool(self.backup),
                "cameras_active": bool(self.cameras is None or getattr(self.cameras, "active", True)),
            }

    # ---------- live feed from the camera workers ----------
    def start_polling(self, interval: float = 0.05):
        threading.Thread(target=self._poll, args=(interval,), name="camcal", daemon=True).start()

    def _poll(self, interval):
        while True:
            if self.phase == "running" and self.cameras is not None:
                now = time.time()
                for cid, w in list(self.cameras.workers.items()):
                    seq = getattr(w, "det_seq", 0)
                    if seq != self._seq.get(cid):
                        self._seq[cid] = seq
                        self.feed(cid, list(w.detections), w.size, now)
                self.tick(now)
            time.sleep(interval)
