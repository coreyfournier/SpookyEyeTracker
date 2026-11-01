import numpy as np
import pytest

from eyetracker.camera import Detection
from eyetracker.world import World


def det(cam, local_id, x, y, face_h=None, ray=None):
    return Detection(cam, local_id, (0, 0, 1, 1), 0.9, (x, y), face_h=face_h, ray=ray)


def test_same_person_from_two_cameras_fuses(store):
    w = World(store)
    w.update("left_to_right", [det("left_to_right", 1, 2.0, 6.0)], 100.0)
    w.update("right_to_left", [det("right_to_left", 7, 2.3, 6.3)], 100.0)
    people = w.people()
    assert len(people) == 1
    assert set(people[0].cams) == {"left_to_right", "right_to_left"}


def test_two_people_stay_separate(store):
    w = World(store)
    w.update("left_to_right", [det("left_to_right", 1, 2, 6), det("left_to_right", 2, -4, 12)], 100.0)
    assert len(w.people()) == 2


def test_track_id_keeps_identity_while_moving(store):
    w = World(store)
    w.update("left_to_right", [det("left_to_right", 1, 0, 5)], 100.0)
    first = w.people()[0].id
    for i in range(1, 10):   # walks 3 m - further than merge_distance from the start
        w.update("left_to_right", [det("left_to_right", 1, i * 0.33, 5)], 100.0 + i * 0.1)
    assert [p.id for p in w.people()] == [first]


def test_people_expire(store):
    w = World(store)
    w.update("left_to_right", [det("left_to_right", 1, 0, 5)], 100.0)
    w.update("left_to_right", [], 100.0 + store.section("tracking")["max_age"] + 0.1)
    assert w.people() == []


def test_mono_height_is_smoothed(store):
    w = World(store)
    w.update("left_to_right", [det("left_to_right", 1, 0, 5, face_h=1.60)], 100.0)
    w.update("left_to_right", [det("left_to_right", 1, 0, 5, face_h=1.20)], 100.1)
    p = w.people()[0]
    assert p.height_src == "mono"
    assert 1.20 < p.face_h < 1.60          # moved toward the new value, not jumped


def test_stereo_height_from_two_cameras(store):
    w = World(store)
    target = np.array([1.0, 8.0, 1.10])     # a child
    o1, o2 = np.array([-6.0, 0, 3]), np.array([6.0, 0, 3])
    r1, r2 = (target - o1) / np.linalg.norm(target - o1), (target - o2) / np.linalg.norm(target - o2)
    w.update("left_to_right", [det("left_to_right", 1, 1.0, 8.0, ray=(o1, r1))], 100.0)
    w.update("right_to_left", [det("right_to_left", 1, 1.0, 8.0, ray=(o2, r2))], 100.05)
    p = w.people()[0]
    assert p.height_src == "stereo"
    assert p.face_h == pytest.approx(1.10, abs=1e-6)


def test_height_measurement_can_be_disabled(store, make_store, cfg_dict):
    cfg_dict["tracking"]["measure_height"] = False
    w = World(make_store(cfg_dict))
    w.update("left_to_right", [det("left_to_right", 1, 0, 5, face_h=1.6)], 100.0)
    assert w.people()[0].face_h is None
