"""Configuration / calibration UI and JSON API."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import onvif
from .config import MAX_CAMERAS, ConfigError, camera_ip, camera_login
from .geometry import DEFAULT_AIM
from .ota import OtaError, detect_board, ota_password, upload as ota_upload
from .version import firmware_status, latest_firmware_version

STATIC = Path(__file__).resolve().parent / "static"
SETTINGS_SECTIONS = ("world", "tracking", "director", "detection", "ui")
# Default identify colours, in config order: cyan, magenta, yellow, green, blue, white.
IDENTIFY_PALETTE = ([0, 255, 255], [255, 0, 255], [255, 200, 0], [0, 255, 0], [0, 60, 255], [255, 255, 255])


def create_app(store, world, link, director, cameras, calib, camcal=None) -> FastAPI:
    """cameras is a CameraManager (it may be inactive when run with --no-cameras);
    camcal is the CameraCalibration wizard."""
    app = FastAPI(title="Animatronic Eye Tracker")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.exception_handler(ConfigError)
    def config_error(_request: Request, exc: ConfigError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def identify_color(eye):
        """The eye's identify_color, else a distinct default by its position in the config."""
        if eye.get("identify_color"):
            return eye["identify_color"]
        ids = [e["id"] for e in store.get()["eyes"]]
        return IDENTIFY_PALETTE[ids.index(eye["id"]) % len(IDENTIFY_PALETTE)]

    def eye_or_404(eye_id):
        eye = store.eye(eye_id)
        if eye is None:
            raise HTTPException(404, f"unknown eye {eye_id}")
        return eye

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/calibrate")
    def calibrate_page():
        return FileResponse(STATIC / "calibrate.html")

    @app.get("/camcal")
    def camcal_page():
        return FileResponse(STATIC / "camcal.html")

    @app.get("/api/config")
    def get_config():
        return store.get()

    def eye_status(eye, latest):
        st = link.status(eye)
        fw = st.setdefault("fw", {})
        if st.get("online"):
            fw["status"] = firmware_status(fw.get("version"), latest)
        fw["latest"] = latest
        return st

    @app.get("/api/state")
    def state():
        cfg = store.get()
        latest = latest_firmware_version()
        return {
            "firmware_latest": latest,
            "cameras": cameras.statuses(),
            "max_cameras": MAX_CAMERAS,
            "cameras_active": cameras.active,
            "people": [p.to_dict(time.time()) for p in world.people()],
            "eyes": {e["id"]: {**eye_status(e, latest), "assignment": director.assignments.get(e["id"])}
                     for e in cfg["eyes"]},
        }

    # ---------- eyes ----------
    @app.post("/api/eyes/{eye_id}/save_push")
    async def save_push(eye_id: str, eye: dict = Body(...)):
        if eye.get("id") != eye_id:
            raise HTTPException(400, "id mismatch")
        store.replace_item("eyes", eye, save=True)
        pushed = await asyncio.to_thread(link.push_config, store.eye(eye_id)) if eye.get("enabled", True) else False
        return {"saved": True, "pushed": pushed}

    @app.post("/api/eyes/{eye_id}/push")
    async def push(eye_id: str):
        pushed = await asyncio.to_thread(link.push_config, eye_or_404(eye_id))
        return {"pushed": pushed}

    @app.post("/api/eyes/{eye_id}/manual")
    def manual(eye_id: str, body: dict = Body(...)):
        link.manual(eye_or_404(eye_id), pan=float(body.get("pan", 0)), tilt=float(body.get("tilt", 0)),
                    lid=float(body.get("lid", 1)), raw=body.get("raw"), hold_s=float(body.get("hold_s", 15)))
        return {"ok": True}

    @app.post("/api/eyes/{eye_id}/release")
    def release(eye_id: str):
        link.release(eye_or_404(eye_id))
        return {"ok": True}

    @app.post("/api/eyes/{eye_id}/firmware")
    async def update_firmware(eye_id: str, request: Request):
        """Body: the raw firmware.bin. Forwarded to the eye's OTA endpoint; the eye reboots."""
        eye = eye_or_404(eye_id)
        image = await request.body()
        try:
            board = detect_board(image)
            running = link.status(eye).get("fw", {}).get("board")
            if running and running != board:
                raise HTTPException(409, f"that firmware is for {board}, but {eye_id} is a {running}")
            reply = await asyncio.to_thread(ota_upload, eye["ip"], image, ota_password())
        except OtaError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "board": board, "eye": reply}

    @app.post("/api/eyes/{eye_id}/identify")
    def identify(eye_id: str, body: dict = Body(...)):
        """{"on": true} lights the eye in its identify colour for hold_s (default 60 s; the UI
        re-sends while the toggle is on, so a closed browser can't leave an eye stuck)."""
        eye = eye_or_404(eye_id)
        rgb = identify_color(eye)
        link.identify(eye, bool(body.get("on", True)), rgb, float(body.get("hold_s", 60)))
        return {"ok": True, "rgb": rgb}

    @app.post("/api/eyes/{eye_id}/look_at")
    def look_at(eye_id: str, body: dict = Body(...)):
        eye_or_404(eye_id)
        director.look_at(eye_id, float(body["x"]), float(body["y"]), float(body.get("seconds", 5)))
        return {"ok": True}

    # ---------- calibrate by pointing ----------
    @app.get("/api/calib/{eye_id}")
    def calib_state(eye_id: str):
        eye = eye_or_404(eye_id)
        servos = eye["firmware"]["servos"]
        return {"target": calib.target_info(eye), "samples": calib.samples(eye), "fit": calib.fit(eye),
                "aim": {**DEFAULT_AIM, **(eye.get("aim") or {})},
                "limits": {a: [servos[a]["min"], servos[a]["max"]] for a in ("pan", "tilt")},
                "eye": link.status(eye)}

    @app.post("/api/calib/{eye_id}/capture")
    def calib_capture(eye_id: str, body: dict = Body(...)):
        try:
            calib.capture(eye_or_404(eye_id), body["pan"], body["tilt"])
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True}

    @app.post("/api/calib/{eye_id}/delete")
    def calib_delete(eye_id: str, body: dict = Body(...)):
        calib.delete(eye_id, int(body["index"]))
        return {"ok": True}

    @app.post("/api/calib/{eye_id}/clear")
    def calib_clear(eye_id: str):
        calib.clear(eye_id)
        return {"ok": True}

    @app.post("/api/calib/{eye_id}/apply")
    def calib_apply(eye_id: str):
        """Save the fitted aim correction on the PC - nothing is pushed to the eye."""
        eye_or_404(eye_id)
        try:
            eye = calib.apply(eye_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"saved": True, "aim": eye["aim"]}

    @app.post("/api/calib/{eye_id}/reset")
    def calib_reset(eye_id: str):
        eye_or_404(eye_id)
        return {"saved": True, "aim": calib.reset(eye_id)["aim"]}

    # ---------- camera calibration wizard ----------
    def wizard():
        if camcal is None:
            raise HTTPException(404, "camera calibration isn't available")
        return camcal

    @app.get("/api/camcal")
    def camcal_status():
        return wizard().status()

    @app.post("/api/camcal/start")
    def camcal_start(body: dict = Body(...)):
        if not cameras.active:
            raise HTTPException(409, "cameras are off (tracker started with --no-cameras)")
        if not cameras.workers:
            raise HTTPException(409, "no cameras are running")
        anchor = body.get("anchor")
        try:
            wizard().start(float(body["height"]), anchor if anchor else None)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return wizard().status()

    @app.post("/api/camcal/{action}")
    def camcal_action(action: str):
        w = wizard()
        actions = {"skip": w.skip, "redo": w.redo, "more": w.more, "cancel": w.cancel,
                   "solve": w.solve, "apply": w.apply, "undo": w.undo}
        if action not in actions:
            raise HTTPException(404, f"unknown action {action}")
        try:
            actions[action]()
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        if action in ("apply", "undo"):
            cameras.sync()
        return w.status()

    # ---------- cameras & settings ----------
    @app.post("/api/cameras")
    def add_camera(cam: dict = Body(...)):
        if not cam.get("id"):
            raise HTTPException(400, "camera id required")
        if store.camera(cam["id"]) is not None:
            raise HTTPException(409, f"camera {cam['id']} already exists")
        store.replace_item("cameras", cam, save=True)   # validate() enforces MAX_CAMERAS
        cameras.sync()
        return {"saved": True}

    @app.post("/api/cameras/{cam_id}/save")
    def save_camera(cam_id: str, cam: dict = Body(...)):
        if cam.get("id") != cam_id or store.camera(cam_id) is None:
            raise HTTPException(400, "unknown camera / id mismatch")
        store.replace_item("cameras", cam, save=True)
        cameras.sync()
        return {"saved": True}

    @app.delete("/api/cameras/{cam_id}")
    def delete_camera(cam_id: str):
        if not store.remove_item("cameras", cam_id, save=True):
            raise HTTPException(404, f"unknown camera {cam_id}")
        cameras.sync()
        return {"deleted": True}

    # ---------- finding cameras (Add camera card) ----------
    @app.get("/api/onvif/discover")
    def onvif_discover():
        """ONVIF cameras that answer a discovery probe on the local network."""
        try:
            return {"cameras": onvif.discover()}
        except OSError as e:
            raise HTTPException(502, f"discovery failed: {e}") from e

    @app.post("/api/onvif/profiles")
    def onvif_profiles(body: dict = Body(...)):
        """A camera's ONVIF stream profiles, using the login from .env (shared, or the camera's own
        username_env / password_env)."""
        cam = {"ip": body.get("ip", ""), "ip_env": body.get("ip_env", ""),
               "username_env": body.get("username_env", ""), "password_env": body.get("password_env", "")}
        if not camera_ip(cam):
            raise HTTPException(400, "ip required")
        user, pw = camera_login(cam, store.section("credentials"))
        try:
            return {"profiles": onvif.Camera(camera_ip(cam), body.get("onvif_port", 80), user, pw).profiles()}
        except onvif.OnvifError as e:
            raise HTTPException(502, str(e)) from e

    @app.get("/api/usb/devices")
    def usb_devices():
        """USB cameras this PC can open (ones a running camera already holds are marked in use)."""
        from .camera import list_usb_cameras   # imported here: it loads OpenCV
        from .config import usb_device
        busy = {usb_device(c) for c in store.section("cameras") or []
                if c.get("type") == "usb" and cameras.get(c["id"]) is not None}
        return {"devices": list_usb_cameras(skip=busy)}

    @app.post("/api/settings/save")
    def save_settings(body: dict = Body(...)):
        data = store.get()
        for key in SETTINGS_SECTIONS:
            if key in body:
                data[key] = body[key]
        store.update(data, save=True)
        return {"saved": True}

    @app.get("/api/cameras/{cam_id}/stream.mjpg")
    def stream(cam_id: str):
        worker = cameras.get(cam_id)
        if worker is None:
            raise HTTPException(404)

        def gen():
            while not worker.stopped:
                jpg = worker.wait_jpeg()
                if jpg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    return app
