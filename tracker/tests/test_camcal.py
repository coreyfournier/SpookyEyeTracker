import copy
from dataclasses import dataclass

import pytest

from eyetracker.camcal import EYE_BELOW_TOP, RECORD_S, STEPS, CameraCalibration, quality, solve
from eyetracker.geometry import CameraModel

SIZE = (2560, 1440)
EYE_H = 1.6
# Where the cameras really are; the config's first guess is off by metres and degrees.
TRUE_POSES = {
    "left_to_right": {"position": [-5.4, -0.4, 2.7], "heading": 47.0, "pitch": -19.0, "roll": 1.5, "hfov": 102.0},
    "right_to_left": {"position": [6.5, 0.3, 3.3], "heading": -34.0, "pitch": -12.0, "roll": -1.0, "hfov": 84.0},
}
SPOTS = [(0.0, 6.0), (-3.0, 6.5), (3.0, 6.0), (0.5, 9.0), (-0.5, 4.5), (2.0, 8.0)]


def true_cams(cfg_dict):
    return [{**c, **TRUE_POSES[c["id"]]} for c in cfg_dict["cameras"]]


def sighting(cam, x, y, eye_h=EYE_H):
    """What a camera at its true pose sees of someone standing at (x, y)."""
    m = CameraModel(cam, *SIZE)
    face, feet = m.project((x, y, eye_h)), m.project((x, y, 0.0))
    if face is None or not (0 <= face[0] < SIZE[0] and 0 <= face[1] < SIZE[1]):
        return None
    if feet is None:
        box = [face[0] - 40, face[1] - 30, face[0] + 40, SIZE[1]]
    else:   # YOLO's box is centred on the body, its bottom edge at the feet (clipped by the frame)
        half = 0.12 * (feet[1] - face[1])
        box = [feet[0] - half, face[1] - 0.08 * (feet[1] - face[1]), feet[0] + half, min(feet[1], SIZE[1])]
    return {"face": list(face), "box": box, "size": list(SIZE)}


def make_spots(cams):
    spots = []
    for x, y in SPOTS:
        obs = {c["id"]: s for c in cams if (s := sighting(c, x, y))}
        spots.append({"obs": obs})
    return spots


def test_synthetic_yard_is_seen_by_both_cameras(cfg_dict):
    spots = make_spots(true_cams(cfg_dict))
    assert sum(len(s["obs"]) == 2 for s in spots) >= 5


def test_solve_recovers_true_poses_from_a_bad_guess(cfg_dict):
    spots = make_spots(true_cams(cfg_dict))
    guess = cfg_dict["cameras"]
    before = quality(guess, spots, EYE_H)
    assert before["camera_gap_m"] > 1.0 or before["height_err_m"] > 0.2   # the guess really is wrong

    r = solve(guess, spots, EYE_H, anchor=SPOTS[0])
    assert r["rms_deg"] < 0.1
    assert r["after"]["camera_gap_m"] < 0.05
    assert r["after"]["height_err_m"] < 0.03
    # Sliding a camera along the house is nearly the same as turning it, so position and
    # heading aren't pinned down individually - but where people end up is.
    for cam in r["cameras"]:
        t = TRUE_POSES[cam["id"]]
        assert cam["heading"] == pytest.approx(t["heading"], abs=4.0)
        assert cam["pitch"] == pytest.approx(t["pitch"], abs=1.0)
        assert cam["hfov"] == pytest.approx(t["hfov"], abs=4.0)
        assert cam["position"][2] == pytest.approx(t["position"][2], abs=0.15)
    for (x, y), est in zip(SPOTS, r["spots_xy"]):
        assert est == pytest.approx([x, y], abs=0.2)


def test_solve_without_anchor_still_makes_cameras_agree(cfg_dict):
    r = solve(cfg_dict["cameras"], make_spots(true_cams(cfg_dict)), EYE_H)
    assert r["after"]["camera_gap_m"] < 0.15
    assert r["after"]["height_err_m"] < 0.05


def test_solve_leaves_a_correct_pose_alone(cfg_dict):
    cams = true_cams(cfg_dict)
    r = solve(cams, make_spots(cams), EYE_H, anchor=SPOTS[0])
    for new, old in zip(r["cameras"], cams):
        assert new["heading"] == pytest.approx(old["heading"], abs=0.05)
        assert new["position"] == pytest.approx(old["position"], abs=0.02)


# ---------------------------------------------------------------- the wizard

@dataclass
class Det:
    face_px: tuple
    box: tuple


class Walker:
    """Drives the wizard like a person walking the yard, at 10 frames per second."""

    def __init__(self, wizard, cams):
        self.w, self.cams, self.t = wizard, cams, 1000.0

    def stand(self, x, y, seconds, crowd=False):
        for _ in range(int(seconds * 10)):
            self.t += 0.1
            for c in self.cams:
                s = sighting(c, x, y)
                dets = [Det(tuple(s["face"]), tuple(s["box"]))] if s else []
                if crowd and dets:
                    dets = dets * 2
                self.w.feed(c["id"], dets, SIZE, self.t)
            self.w.tick(self.t)


@pytest.fixture
def wizard(store):
    return CameraCalibration(store)


def test_wizard_walks_through_every_spot_then_solves_and_applies(wizard, store, cfg_dict):
    cams = true_cams(cfg_dict)
    wizard.start(EYE_H + EYE_BELOW_TOP, anchor=SPOTS[0])
    walker = Walker(wizard, cams)
    for i, (x, y) in enumerate(SPOTS):
        assert wizard.phase == "running" and wizard.index == i
        walker.stand(x, y, 1.5 + RECORD_S + 0.5)
        assert len(wizard.spots) == i + 1, wizard.message
    assert wizard.phase == "review"
    assert wizard.status()["spots"][0] == {"title": "Center spot", "cams": sorted(TRUE_POSES)}

    r = wizard.solve()
    assert wizard.phase == "solved" and r["after"]["camera_gap_m"] < 0.1
    wizard.apply()
    left = store.camera("left_to_right")
    assert left["heading"] == pytest.approx(47.0, abs=4.0)
    assert wizard.status()["can_undo"]

    wizard.undo()
    assert store.camera("left_to_right")["heading"] == cfg_dict["cameras"][0]["heading"]
    assert not wizard.status()["can_undo"]


def test_wizard_waits_for_you_to_move_and_hold_still(wizard, cfg_dict):
    cams = true_cams(cfg_dict)
    wizard.start(1.7)
    walker = Walker(wizard, cams)
    walker.stand(*SPOTS[0], 0.8)
    assert wizard.sub == "settle" and not wizard.spots       # not still for long enough yet
    walker.stand(*SPOTS[0], 3.5)
    assert len(wizard.spots) == 1 and wizard.sub == "move"
    walker.stand(*SPOTS[0], 5)                                # didn't walk anywhere
    assert len(wizard.spots) == 1 and "next spot" in wizard.message
    # walking: a new position every frame never counts as still
    for k in range(30):
        walker.stand(-k * 0.1, 6.0, 0.1)
    assert len(wizard.spots) == 1
    walker.stand(*SPOTS[1], 4)
    assert len(wizard.spots) == 2


def test_wizard_ignores_frames_with_someone_else_in_view(wizard, cfg_dict):
    wizard.start(1.7)
    Walker(wizard, true_cams(cfg_dict)).stand(*SPOTS[0], 5, crowd=True)
    assert not wizard.spots and "Someone else" in wizard.message


def test_wizard_cant_see_you(wizard):
    wizard.start(1.7)
    wizard.tick(5.0)
    assert "can't see you" in wizard.message


def test_skip_redo_and_more(wizard, cfg_dict):
    cams = true_cams(cfg_dict)
    wizard.start(1.7)
    walker = Walker(wizard, cams)
    walker.stand(*SPOTS[0], 4)
    wizard.skip()
    assert wizard.index == 2 and len(wizard.spots) == 1
    wizard.redo()                                            # throw the center spot away
    assert wizard.index == 0 and not wizard.spots
    for _ in STEPS:
        wizard.skip()
    assert wizard.phase == "review"
    wizard.more()
    assert wizard.phase == "running" and wizard.status()["step"]["key"] == "extra"


def test_solve_needs_three_spots(wizard):
    wizard.start(1.7)
    with pytest.raises(ValueError, match="at least 3"):
        wizard.solve()


def test_start_rejects_height_in_feet(wizard):
    with pytest.raises(ValueError, match="metres"):
        wizard.start(5.9)


def test_backup_survives_a_restart(wizard, store, cfg_dict):
    wizard.start(EYE_H + EYE_BELOW_TOP, anchor=SPOTS[0])
    wizard.spots = [{**s, "step": i, "key": STEPS[i][0], "title": STEPS[i][1]}
                    for i, s in enumerate(make_spots(true_cams(cfg_dict)))]
    wizard.solve()
    wizard.apply()
    again = CameraCalibration(store)
    assert again.status()["can_undo"]
    again.undo()
    assert store.camera("right_to_left")["position"] == cfg_dict["cameras"][1]["position"]


# ---------------------------------------------------------------- API

def test_api_refuses_to_start_without_cameras(app):
    assert app.get("/camcal").status_code == 200
    assert app.get("/api/camcal").json()["phase"] == "idle"
    r = app.post("/api/camcal/start", json={"height": 1.75})
    assert r.status_code == 409 and "cameras" in r.json()["detail"]


def test_api_actions(app):
    assert app.post("/api/camcal/solve").status_code == 409     # nothing recorded
    assert app.post("/api/camcal/undo").status_code == 409
    assert app.post("/api/camcal/bogus").status_code == 404
    assert app.post("/api/camcal/cancel").json()["phase"] == "idle"


def test_api_start_with_a_running_camera(app):
    app.cameras.active = True
    app.cameras.workers["left_to_right"] = object()
    r = app.post("/api/camcal/start", json={"height": 1.75, "anchor": [0, 6]})
    assert r.status_code == 200, r.text
    assert r.json()["phase"] == "running" and r.json()["anchor"] == [0, 6]
    assert r.json()["eye_height"] == pytest.approx(1.75 - EYE_BELOW_TOP)
    assert app.post("/api/camcal/start", json={"height": 175}).status_code == 400
