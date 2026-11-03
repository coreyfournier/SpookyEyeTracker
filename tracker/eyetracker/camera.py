"""Per-camera video reader + YOLO person detector.

Each camera gets two threads: a reader that always keeps only the newest frame
(so detection never lags behind a growing buffer) and a detector that runs YOLO
tracking on that frame and feeds world positions into the World tracker.
Cameras are Hikvision, ONVIF or plain RTSP network cameras, or USB cameras (see open_source).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from . import onvif  # noqa: E402
from .config import (ConfigStore, camera_ip, camera_login, custom_url, redact, rtsp_url,  # noqa: E402
                     usb_device)
from .geometry import CameraModel  # noqa: E402

log = logging.getLogger(__name__)
USB_BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY   # DirectShow opens webcams fastest on Windows


def stream_source(cam: dict, creds: dict) -> tuple[int | str, str]:
    """Where to read a camera from, and how to show it in the log (password hidden).
    ONVIF asks the camera over the network, so it can raise onvif.OnvifError."""
    kind = cam.get("type", "hikvision")
    if kind == "usb":
        dev = usb_device(cam)
        return dev, f"USB camera {dev}"
    user, pw = camera_login(cam, creds)
    if kind == "onvif":
        url = onvif.Camera(camera_ip(cam), cam.get("onvif_port", 80), user, pw).stream_uri(cam.get("profile", ""))
    elif kind == "rtsp":
        url = custom_url(cam, creds)
    else:
        url = rtsp_url(cam, creds)
    return url, redact(url, pw)


def open_source(src: int | str, cam: dict):
    """cv2.VideoCapture for a stream URL or a USB camera (at its configured resolution)."""
    if isinstance(src, int) or cam.get("type") == "usb":
        cap = cv2.VideoCapture(src, USB_BACKEND)
        if cam.get("width") and cam.get("height"):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cam["width"]))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cam["height"]))
        return cap
    return cv2.VideoCapture(src, cv2.CAP_FFMPEG)


def list_usb_cameras(max_index: int = 6, skip=()) -> list[dict]:
    """USB cameras this PC can open, as [{device, width, height}]. Indices in `skip` (already in
    use by a running camera, which would block opening them again) are listed without probing."""
    found = []
    for i in range(max_index):
        if i in skip:
            found.append({"device": i, "width": 0, "height": 0, "in_use": True})
            continue
        cap = cv2.VideoCapture(i, USB_BACKEND)
        try:
            if cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None:
                    found.append({"device": i, "width": frame.shape[1], "height": frame.shape[0], "in_use": False})
        finally:
            cap.release()
    return found

PREVIEW_WIDTH = 960


KP_CONF = 0.5
# COCO keypoint indices
NOSE, L_EYE, R_EYE, L_EAR, R_EAR, L_SHOULDER, R_SHOULDER = range(7)
EYE_FRACTION = 1 / 16       # eyes sit ~1/16 of body height below the top of the head
SHOULDER_FRACTION = 0.36    # eyes are ~36% of the way from head top down to the shoulders


def face_pixel(box, kps, full_body: bool):
    """Pixel of the person's eyes. kps = (17, 3) array of x, y, conf, or None."""
    x1, y1, x2, y2 = box
    cx = (x1 + x2) / 2
    if kps is not None:
        for group in ((NOSE, L_EYE, R_EYE), (L_EAR, R_EAR)):
            pts = [kps[i, :2] for i in group if kps[i, 2] >= KP_CONF]
            if pts:
                return tuple(np.mean(pts, axis=0))
        sh = [kps[i, :2] for i in (L_SHOULDER, R_SHOULDER) if kps[i, 2] >= KP_CONF]
        if sh:
            sx, sy = np.mean(sh, axis=0)
            return sx, y1 + SHOULDER_FRACTION * (sy - y1)
    if full_body:
        return cx, y1 + EYE_FRACTION * (y2 - y1)
    # Lower body cut off - the box height isn't the body height, use a head-sized offset.
    return cx, y1 + 0.12 * (x2 - x1)


@dataclass
class Detection:
    cam_id: str
    local_id: int          # YOLO/ByteTrack id within this camera (-1 if untracked)
    box: tuple             # x1, y1, x2, y2 in frame pixels
    conf: float
    world: tuple           # x, y metres
    face_px: tuple = (0.0, 0.0)
    face_h: float | None = None   # measured eye-level height (m)
    ray: tuple = None             # (origin, unit dir) through the face, for triangulation
    world_id: int = -1            # filled in by World


class CameraWorker:
    def __init__(self, cam_id: str, store: ConfigStore, world, model_factory):
        self.cam_id = cam_id
        self.store = store
        self.world = world
        self.model_factory = model_factory
        self._frame = None
        self._frame_seq = 0
        self._frame_lock = threading.Condition()
        self._jpeg = None
        self._jpeg_lock = threading.Condition()
        self._stop = threading.Event()
        self.connected = False
        self.error = ""          # why it isn't connected, for the UI
        self.read_fps = 0.0
        self.detect_fps = 0.0
        self.size = (0, 0)
        self.detections: list[Detection] = []
        self.det_seq = 0   # bumps with every processed frame (the calibration wizard polls it)

    # ---------- lifecycle ----------
    def start(self):
        threading.Thread(target=self._read_loop, name=f"read-{self.cam_id}", daemon=True).start()
        threading.Thread(target=self._detect_loop, name=f"detect-{self.cam_id}", daemon=True).start()

    def stop(self):
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # ---------- reader ----------
    def _read_loop(self):
        while not self._stop.is_set():
            cam = self.store.camera(self.cam_id)
            if cam is None:  # removed from config; the manager stops us
                return
            try:
                src, shown = stream_source(cam, self.store.section("credentials"))
            except onvif.OnvifError as e:
                log.warning("%s: %s - retrying in 10s", self.cam_id, e)
                self.connected, self.error = False, str(e)
                self._stop.wait(10)
                continue
            log.info("%s: opening %s", self.cam_id, shown)
            cap = open_source(src, cam)
            if not cap.isOpened():
                log.warning("%s: could not open %s, retrying in 5s", self.cam_id, shown)
                self.connected, self.error = False, f"could not open {shown}"
                cap.release()
                self._stop.wait(5)
                continue
            self.connected, self.error = True, ""
            n, t0 = 0, time.time()
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    log.warning("%s: stream dropped, reconnecting", self.cam_id)
                    self.error = "stream dropped, reconnecting"
                    break
                with self._frame_lock:
                    self._frame = frame
                    self._frame_seq += 1
                    self._frame_lock.notify_all()
                n += 1
                if time.time() - t0 >= 2:
                    self.read_fps = n / (time.time() - t0)
                    n, t0 = 0, time.time()
            self.connected = False
            cap.release()
            time.sleep(1)

    # ---------- detector ----------
    def _detect_loop(self):
        model = self.model_factory()
        device = None
        last_seq, model_rev, cam_model = 0, -1, None
        n, t0 = 0, time.time()
        while not self._stop.is_set():
            with self._frame_lock:
                self._frame_lock.wait_for(lambda: self._frame_seq != last_seq or self._stop.is_set(), timeout=1)
                if self._frame_seq == last_seq:
                    continue
                frame, last_seq = self._frame, self._frame_seq

            cfg = self.store.get()
            cam = next((c for c in cfg["cameras"] if c["id"] == self.cam_id), None)
            if cam is None:
                return
            h, w = frame.shape[:2]
            if cam_model is None or model_rev != self.store.revision or (w, h) != self.size:
                cam_model, model_rev, self.size = CameraModel(cam, w, h), self.store.revision, (w, h)

            det_cfg = cfg["detection"]
            if device is None or model_rev != self.store.revision:
                device = resolve_device(det_cfg.get("device", "auto"))
            results = model.track(frame, persist=True, classes=[0], conf=det_cfg["confidence"],
                                  imgsz=det_cfg["imgsz"], device=device, verbose=False,
                                  tracker="bytetrack.yaml")
            dets = []
            boxes = results[0].boxes
            if boxes is not None and len(boxes):
                xyxy = boxes.xyxy.cpu().numpy()
                confs = boxes.conf.cpu().numpy()
                ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else [-1] * len(xyxy)
                kps = results[0].keypoints.data.cpu().numpy() if results[0].keypoints is not None else None
                for i, (box, conf, tid) in enumerate(zip(xyxy, confs, ids)):
                    fpx = face_pixel(box, kps[i] if kps is not None and len(kps) > i else None,
                                     cam_model.feet_visible(box))
                    loc = cam_model.locate(box, fpx, cfg["world"]["look_height"])
                    dets.append(Detection(self.cam_id, int(tid), tuple(map(float, box)), float(conf),
                                          (float(loc.x), float(loc.y)), tuple(map(float, fpx)), loc.face_h,
                                          (loc.ray_o, loc.ray_d)))
            self.world.update(self.cam_id, dets, time.time())
            self.detections = dets
            self.det_seq += 1
            self._publish_preview(frame, dets, cam_model, cfg)

            n += 1
            if time.time() - t0 >= 2:
                self.detect_fps = n / (time.time() - t0)
                n, t0 = 0, time.time()

    # ---------- preview ----------
    def _publish_preview(self, frame, dets, cam_model, cfg):
        img = frame.copy()
        scale = PREVIEW_WIDTH / img.shape[1] if img.shape[1] > PREVIEW_WIDTH else 1.0
        # ground grid every 2 m helps judge whether the pose guess is right
        for gx in np.arange(-20, 21, 2.0):
            self._polyline(img, cam_model, [(gx, gy, 0) for gy in np.arange(0, 30.5, 0.5)], (60, 60, 60))
        for gy in np.arange(0, 31, 2.0):
            self._polyline(img, cam_model, [(gx, gy, 0) for gx in np.arange(-20, 20.5, 0.5)], (60, 60, 60))
        for e in cfg["eyes"]:
            p = cam_model.project(e["position"])
            if p:
                cv2.drawMarker(img, (int(p[0]), int(p[1])), (255, 200, 0), cv2.MARKER_STAR, 30, 3)
        heights = {p.id: p.face_h for p in self.world.people()}
        for d in dets:
            x1, y1, x2, y2 = map(int, d.box)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), max(2, int(2 / scale)))
            cv2.circle(img, (int(d.face_px[0]), int(d.face_px[1])), max(4, int(5 / scale)), (0, 255, 255), -1)
            h = heights.get(d.world_id)
            label = f"#{d.world_id} ({d.world[0]:.1f},{d.world[1]:.1f})m eyes {f'{h:.2f}m' if h else '?'}"
            cv2.putText(img, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6 / scale,
                        (0, 0, 255), max(1, int(2 / scale)))
        if scale != 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with self._jpeg_lock:
                self._jpeg = jpg.tobytes()
                self._jpeg_lock.notify_all()

    @staticmethod
    def _polyline(img, cam_model, pts, color):
        px = [cam_model.project(p) for p in pts]
        h, w = img.shape[:2]
        prev = None
        for p in px:
            if p is not None and -w < p[0] < 2 * w and -h < p[1] < 2 * h:
                q = (int(p[0]), int(p[1]))
                if prev is not None:
                    cv2.line(img, prev, q, color, 1)
                prev = q
            else:
                prev = None

    def wait_jpeg(self, timeout=2.0):
        with self._jpeg_lock:
            self._jpeg_lock.wait(timeout)
            return self._jpeg

    def status(self) -> dict:
        return {"id": self.cam_id, "enabled": True, "connected": self.connected, "read_fps": round(self.read_fps, 1),
                "detect_fps": round(self.detect_fps, 1), "size": self.size,
                "people": len(self.detections), "error": self.error}


def resolve_device(device) -> str:
    """'auto' -> first CUDA GPU if PyTorch can see one, else CPU."""
    device = str(device)
    if device != "auto":
        return device
    import torch  # imported lazily: only the detector needs it
    return "0" if torch.cuda.is_available() else "cpu"


# changing any of these restarts the camera's stream (pose edits apply live)
STREAM_KEYS = ("type", "ip", "ip_env", "rtsp_port", "channel", "onvif_port", "profile", "url", "device",
               "width", "height", "username_env", "password_env")


def stream_key(cam: dict) -> tuple:
    return tuple(cam.get(k) for k in STREAM_KEYS)


class CameraManager:
    """Keeps one CameraWorker per enabled camera in the config (0..MAX_CAMERAS).

    Call sync() after the camera list changes: removed/disabled cameras stop, new ones
    start, and a camera whose stream settings changed is restarted. Pose edits apply live.
    """

    def __init__(self, store: ConfigStore, world, model_factory, worker_cls=None, active: bool = True):
        self.store = store
        self.world = world
        self.model_factory = model_factory
        self.active = active  # False with --no-cameras: config edits are saved but nothing streams
        self.worker_cls = worker_cls or CameraWorker
        self.workers: dict[str, CameraWorker] = {}
        self._keys: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def sync(self):
        if not self.active:
            return
        cams = {c["id"]: c for c in self.store.section("cameras") or [] if c.get("enabled", True)}
        with self._lock:
            for cid in list(self.workers):
                if cid not in cams or self._keys[cid] != stream_key(cams[cid]):
                    log.info("%s: stopping", cid)
                    self.workers.pop(cid).stop()
                    del self._keys[cid]
            for cid, cam in cams.items():
                if cid not in self.workers:
                    w = self.worker_cls(cid, self.store, self.world, self.model_factory)
                    w.start()
                    self.workers[cid] = w
                    self._keys[cid] = stream_key(cam)

    def get(self, cam_id: str):
        return self.workers.get(cam_id)

    def statuses(self) -> list[dict]:
        out = []
        for cam in self.store.section("cameras") or []:
            w = self.workers.get(cam["id"])
            out.append(w.status() if w else {"id": cam["id"], "connected": False, "enabled": False,
                                             "read_fps": 0, "detect_fps": 0, "size": (0, 0), "people": 0,
                                             "error": ""})
        return out
