import pytest



def test_pages_and_state(app):
    assert app.get("/").status_code == 200
    assert app.get("/calibrate").status_code == 200
    state = app.get("/api/state").json()
    assert state["max_cameras"] == 2 and len(state["cameras"]) == 2
    assert state["eyes"]["eye1"]["online"]


def test_state_reports_firmware_status(app, monkeypatch):
    monkeypatch.setenv("EYETRACKER_FIRMWARE_VERSION", "2222222")
    fw = app.get("/api/state").json()["eyes"]["eye1"]["fw"]
    assert fw["status"] == "outdated" and fw["latest"] == "2222222" and fw["version"] == "1111111"
    monkeypatch.setenv("EYETRACKER_FIRMWARE_VERSION", "1111111")
    assert app.get("/api/state").json()["eyes"]["eye1"]["fw"]["status"] == "current"


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
    r = app.post("/api/calib/eye1/capture", json={"pan": 0, "tilt": 0})
    assert r.status_code == 409
    state = app.get("/api/calib/eye1").json()
    assert state["target"] is None and state["samples"] == []
    assert state["aim"]["pan_scale"] == 1.0 and state["limits"]["pan"] == [-25.0, 25.0]


def test_calibration_apply_saves_aim_without_pushing(app, store):
    from eyetracker.world import Person
    app.app_world.people = lambda max_age=None: [Person(1, 0, 6, 0, 0, face_h=1.6)]
    assert app.post("/api/calib/eye1/capture", json={"pan": 3, "tilt": -1}).status_code == 200
    r = app.post("/api/calib/eye1/apply").json()
    assert r["saved"] and r["aim"]["pan_offset"] == pytest.approx(3, abs=0.01)
    assert store.eye("eye1")["aim"]["pan_offset"] == pytest.approx(3, abs=0.01)
    assert app.link.pushed == []                       # aim lives on the PC only
    assert app.post("/api/calib/eye1/reset").json()["aim"]["pan_offset"] == 0.0


def test_settings_save(app, store):
    r = app.post("/api/settings/save", json={"director": dict(store.section("director"), strategy="spread")})
    assert r.status_code == 200 and store.section("director")["strategy"] == "spread"


def test_firmware_upload_checks_board_before_sending(app):
    heltec = bytes([0xE9]) + b"heltec_wifi_kit_32_v2\0" + b"x" * 100
    r = app.post("/api/eyes/eye1/firmware", content=heltec)
    assert r.status_code == 409 and "featheresp32" in r.json()["detail"]   # the fake eye reports a Feather


def test_firmware_upload_rejects_non_firmware(app):
    r = app.post("/api/eyes/eye1/firmware", content=b"definitely not firmware")
    assert r.status_code == 400 and "not an ESP32 firmware image" in r.json()["detail"]


def test_identify_uses_the_eyes_colour(app):
    r = app.post("/api/eyes/eye2/identify", json={"on": True}).json()
    assert r["rgb"] == [255, 0, 255]                         # identify_color from the config
    app.post("/api/eyes/eye2/identify", json={"on": False})
    assert app.link.identifies == [("eye2", True, [255, 0, 255], 60.0), ("eye2", False, [255, 0, 255], 60.0)]


def test_identify_colour_defaults_by_position(app, store):
    eye = store.eye("eye2")
    eye.pop("identify_color")
    store.replace_item("eyes", eye, save=False)
    assert app.post("/api/eyes/eye2/identify", json={"on": True}).json()["rgb"] == [255, 0, 255]   # 2nd default
