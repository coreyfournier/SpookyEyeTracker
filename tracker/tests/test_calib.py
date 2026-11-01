import json

import numpy as np
import pytest

from eyetracker.calib import Calibrator
from eyetracker.geometry import eye_angles
from eyetracker.world import Person


class FakeWorld:
    def __init__(self, people=()):
        self.list = list(people)

    def people(self, max_age=None):
        return self.list


def test_single_sample_fits_offset_only():
    f = Calibrator._fit_axis([10.0], [1800.0], 30.0, 8.0)
    assert f["mode"] == "offset" and f["us_per_deg"] == 30.0 and f["center"] == 1500


def test_spread_samples_fit_scale_and_reversed_servo():
    deg = np.array([-20, -5, 0, 10, 20.0])
    us = 1430 - 26 * deg
    f = Calibrator._fit_axis(list(deg), list(us), 30.0, 8.0)
    assert f["mode"] == "offset+scale"
    assert f["center"] == 1430 and f["us_per_deg"] == pytest.approx(-26)
    assert f["rms_us"] == pytest.approx(0, abs=0.01)


def test_implausible_scale_falls_back_to_offset():
    f = Calibrator._fit_axis([0, 10], [1500, 1505], 30.0, 8.0)   # 0.5 us/deg - nonsense
    assert f["mode"].startswith("offset (scale fit implausible")
    assert f["us_per_deg"] == 30.0


def test_no_samples():
    assert Calibrator._fit_axis([], [], 30.0, 8.0) is None


def test_capture_requires_a_person(store):
    cal = Calibrator(store, FakeWorld())
    with pytest.raises(ValueError):
        cal.capture(store.eye("eye1"), 1500, 1500)


def test_capture_fit_apply_end_to_end(store):
    world = FakeWorld()
    cal = Calibrator(store, world)
    eye = store.eye("eye1")
    true_center, true_scale = 1580, 24.0
    for x, y in [(0, 6), (-5, 8), (5, 8), (2, 4)]:
        world.list = [Person(1, x, y, 0, 0, face_h=1.6)]
        pan, tilt = eye_angles(eye, (x, y), 1.6)
        cal.capture(eye, round(true_center + true_scale * pan), round(1500 + 30 * tilt))
    fit = cal.fit(eye)
    assert fit["pan"]["center"] == pytest.approx(true_center, abs=2)
    assert fit["pan"]["us_per_deg"] == pytest.approx(true_scale, abs=0.2)

    cal.apply("eye1")
    servos = store.eye("eye1")["firmware"]["servos"]
    assert servos["pan"]["center"] == fit["pan"]["center"]
    saved = json.loads(cal.samples_file.read_text())
    assert len(saved["eye1"]) == 4 and cal.samples_file.parent == store.path.parent


def test_delete_and_clear(store):
    world = FakeWorld([Person(1, 0, 5, 0, 0)])
    cal = Calibrator(store, world)
    eye = store.eye("eye1")
    cal.capture(eye, 1500, 1500)
    cal.capture(eye, 1510, 1500)
    cal.delete("eye1", 0)
    assert [s["pan_us"] for s in cal.samples(eye)] == [1510]
    cal.clear("eye1")
    assert cal.samples(eye) == []
