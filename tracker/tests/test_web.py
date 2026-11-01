import pytest
from fastapi.testclient import TestClient

from eyetracker.calib import Calibrator
from eyetracker.camera import CameraManager
from eyetracker.director import Director
from eyetracker.web import create_app
from eyetracker.world import World


class FakeLink:
    def __init__(self):
        self.pushed, self.manuals = [], []

    def push_config(self, eye, **_):
        self.pushed.append(eye["id"])
        return True

    def status(self, eye):
        return {"online": True, "state": "idle", "config_in_sync": True}

    def manual(self, eye, **kw):
        self.manuals.append(kw)

    def release(self, eye):
        pass

    def look(self, *a, **kw):
        pass


@pytest.fixture
def app(store):
    world = World(store)
    link = FakeLink()
    cameras = CameraManager(store, world, None, active=False)
    client = TestClient(create_app(store, world, link, Director(store, world, link), cameras,
                                   Calibrator(store, world)))
    client.link = link
    return client


def test_pages_and_state(app):
    assert app.get("/").status_code == 200
    assert app.get("/calibrate").status_code == 200
    state = app.get("/api/state").json()
    assert state["max_cameras"] == 2 and len(state["cameras"]) == 2
    assert state["eyes"]["eye1"]["online"]


def test_third_camera_is_rejected(app):
    cam = dict(app.get("/api/config").json()["cameras"][0], id="third")
    r = app.post("/api/cameras", json=cam)
    assert r.status_code == 400 and "at most 2 cameras" in r.json()["detail"]


def test_remove_then_add_camera(app, store):
    assert app.delete("/api/cameras/left_to_right").status_code == 200
    assert app.delete("/api/cameras/left_to_right").status_code == 404
    cam = {"id": "garage", "ip": "192.168.4.70", "position": [0, 0, 3], "heading": 0, "pitch": -15, "hfov": 90}
    assert app.post("/api/cameras", json=cam).status_code == 200
    assert [c["id"] for c in store.get()["cameras"]] == ["right_to_left", "garage"]
    assert app.post("/api/cameras", json=cam).status_code == 409    # duplicate id


def test_save_camera_id_mismatch(app):
    cam = app.get("/api/config").json()["cameras"][0]
    assert app.post("/api/cameras/other/save", json=cam).status_code == 400


def test_eye_save_push_and_push(app, store):
    eye = app.get("/api/config").json()["eyes"][0]
    eye["firmware"]["behaviors"]["spooky"]["enabled"] = True
    r = app.post("/api/eyes/eye1/save_push", json=eye).json()
    assert r == {"saved": True, "pushed": True}
    assert store.eye("eye1")["firmware"]["behaviors"]["spooky"]["enabled"] is True
    assert app.post("/api/eyes/eye1/push").json() == {"pushed": True}
    assert app.link.pushed == ["eye1", "eye1"]


def test_unknown_eye_404(app):
    assert app.post("/api/eyes/nope/push").status_code == 404


def test_calibration_capture_needs_person(app):
    r = app.post("/api/calib/eye1/capture", json={"pan_us": 1500, "tilt_us": 1500})
    assert r.status_code == 409
    state = app.get("/api/calib/eye1").json()
    assert state["target"] is None and state["samples"] == []


def test_settings_save(app, store):
    r = app.post("/api/settings/save", json={"director": dict(store.section("director"), strategy="spread")})
    assert r.status_code == 200 and store.section("director")["strategy"] == "spread"
