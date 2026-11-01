import json

import numpy as np
import pytest

from eyetracker.calib import Calibrator
from eyetracker.config import firmware_version
from eyetracker.geometry import DEFAULT_AIM, eye_angles
from eyetracker.world import Person


class FakeWorld:
    def __init__(self, people=()):
        self.list = list(people)

    def people(self, max_age=None):
        return self.list


def test_single_sample_fits_offset_only():
    f = Calibrator._fit_axis([10.0], [13.0], 1.0, 8.0)
    assert f["mode"] == "offset" and f["scale"] == 1.0 and f["offset"] == pytest.approx(3.0)


def test_spread_samples_fit_offset_and_scale():
    geo = np.array([-20, -5, 0, 10, 20.0])
    cmd = 2.5 + 0.8 * geo
    f = Calibrator._fit_axis(list(geo), list(cmd), 1.0, 8.0)
    assert f["mode"] == "offset+scale"
    assert f["offset"] == pytest.approx(2.5) and f["scale"] == pytest.approx(0.8)
    assert f["rms_deg"] == pytest.approx(0, abs=0.01)


def test_implausible_scale_falls_back_to_offset():
    f = Calibrator._fit_axis([0, 10], [0, -10], 1.0, 8.0)   # negative scale = reversed servo, not aim
    assert f["mode"].startswith("offset (scale fit implausible")
    assert f["scale"] == 1.0


def test_no_samples():
    assert Calibrator._fit_axis([], [], 1.0, 8.0) is None


def test_capture_requires_a_person(store):
    with pytest.raises(ValueError):
        Calibrator(store, FakeWorld()).capture(store.eye("eye1"), 0, 0)


def test_capture_fit_apply_end_to_end(store):
    world = FakeWorld()
    cal = Calibrator(store, world)
    eye = store.eye("eye1")
    fw_before = firmware_version(eye["firmware"])
    for x, y in [(0, 6), (-5, 8), (5, 8), (2, 4)]:
        world.list = [Person(1, x, y, 0, 0, face_h=1.6)]
        pan, tilt = eye_angles(eye, (x, y), 1.6)
        cal.capture(eye, 4.0 + 0.9 * pan, -2.0 + tilt)       # cameras are off by a bit
    fit = cal.fit(eye)
    assert fit["pan"]["offset"] == pytest.approx(4.0, abs=0.05)
    assert fit["pan"]["scale"] == pytest.approx(0.9, abs=0.01)

    cal.apply("eye1")
    saved = store.eye("eye1")
    assert saved["aim"]["pan_offset"] == fit["pan"]["offset"]
    assert saved["aim"]["tilt_offset"] == pytest.approx(-2.0, abs=0.05)
    # the eye's mechanical calibration is untouched -> nothing needs pushing
    assert firmware_version(saved["firmware"]) == fw_before
    assert len(json.loads(cal.samples_file.read_text())["eye1"]) == 4

    cal.reset("eye1")
    assert store.eye("eye1")["aim"] == DEFAULT_AIM


def test_old_microsecond_samples_are_ignored(store):
    cal = Calibrator(store, FakeWorld())
    cal._samples = {"eye1": [{"x": 0, "y": 5, "face_h": None, "pan_us": 1500, "tilt_us": 1500}]}
    assert cal.samples(store.eye("eye1")) == []
    with pytest.raises(ValueError):
        cal.apply("eye1")


def test_delete_and_clear(store):
    cal = Calibrator(store, FakeWorld([Person(1, 0, 5, 0, 0)]))
    eye = store.eye("eye1")
    cal.capture(eye, 1.0, 0)
    cal.capture(eye, 2.0, 0)
    cal.delete("eye1", 0)
    assert [s["pan_cmd"] for s in cal.samples(eye)] == [2.0]
    cal.clear("eye1")
    assert cal.samples(eye) == []
