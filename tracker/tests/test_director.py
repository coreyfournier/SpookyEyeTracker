import pytest

from eyetracker.director import STRATEGIES, Director
from eyetracker.world import Person


def person(pid, x, y, face_h=None):
    return Person(pid, x, y, 0, 0, face_h=face_h)


def test_closest_picks_nearest(cfg_dict):
    eye = cfg_dict["eyes"][0]
    picks = STRATEGIES["closest"]([eye], [person(1, 0, 10), person(2, 1, 4)], {}, cfg_dict)
    assert picks[eye["id"]][1].id == 2


def test_hysteresis_keeps_current_target(cfg_dict):
    eye = cfg_dict["eyes"][0]
    people = [person(1, 0, 5), person(2, 0, 4)]           # #2 is 1 m closer, under switch_margin
    picks = STRATEGIES["closest"]([eye], people, {eye["id"]: 1}, cfg_dict)
    assert picks[eye["id"]][1].id == 1


def test_switches_when_much_closer(cfg_dict):
    eye = cfg_dict["eyes"][0]
    people = [person(1, 0, 12), person(2, 0, 4)]
    picks = STRATEGIES["closest"]([eye], people, {eye["id"]: 1}, cfg_dict)
    assert picks[eye["id"]][1].id == 2


def test_ignores_people_beyond_max_pan(cfg_dict):
    eye = cfg_dict["eyes"][0]
    cfg_dict["director"]["max_pan"] = 45
    picks = STRATEGIES["closest"]([eye], [person(1, 10, 1)], {}, cfg_dict)   # ~84 deg to the side
    assert picks[eye["id"]] is None


def test_spread_gives_eyes_different_people(cfg_dict):
    eye1 = cfg_dict["eyes"][0]
    eye2 = dict(eye1, id="eye2", position=[3, 0.3, 1.2])
    people = [person(1, 1, 5), person(2, -3, 8)]
    picks = STRATEGIES["spread"]([eye1, eye2], people, {}, cfg_dict)
    assert {picks["eye1"][1].id, picks["eye2"][1].id} == {1, 2}


def test_measured_height_changes_tilt(cfg_dict):
    eye = cfg_dict["eyes"][0]
    adult = STRATEGIES["closest"]([eye], [person(1, 0, 5, face_h=1.7)], {}, cfg_dict)[eye["id"]]
    child = STRATEGIES["closest"]([eye], [person(1, 0, 5, face_h=1.0)], {}, cfg_dict)[eye["id"]]
    assert adult[3] > child[3]


class FakeLink:
    def __init__(self):
        self.looks = []

    def look(self, eye, target, pan=0, tilt=0, new=False):
        self.looks.append((eye["id"], target, round(pan, 1), round(tilt, 1), new))

    def status(self, eye):
        return {"online": False, "config_in_sync": False}


class FakeWorld:
    def __init__(self, people):
        self._people = people

    def people(self, max_age=None):
        return self._people


def test_tick_sends_look_and_flags_new_target(store):
    link = FakeLink()
    d = Director(store, FakeWorld([person(1, 0, 5)]), link)
    d._tick(store.get())
    d._tick(store.get())
    assert [l[4] for l in link.looks] == [True, False]     # "new" only on acquisition
    assert link.looks[0][1] is True


def test_tick_without_people_sends_no_target(store):
    link = FakeLink()
    Director(store, FakeWorld([]), link)._tick(store.get())
    assert link.looks == [("eye1", False, 0, 0, False)]


def test_aim_correction_is_applied_to_sent_angles(store):
    eye = store.eye("eye1")
    eye["aim"] = {"pan_offset": 5.0, "pan_scale": 0.5, "tilt_offset": -1.0, "tilt_scale": 1.0}
    store.replace_item("eyes", eye, save=False)
    link = FakeLink()
    d = Director(store, FakeWorld([]), link)
    d.look_at("eye1", 5, 8)                                 # geometric pan 33.0 deg
    d._tick(store.get())
    assert link.looks[0][2] == pytest.approx(5.0 + 0.5 * 33.0, abs=0.1)


def test_look_at_override(store):
    link = FakeLink()
    d = Director(store, FakeWorld([]), link)
    d.look_at("eye1", 5, 8)
    d._tick(store.get())
    _, target, pan, _, _ = link.looks[0]
    assert target and pan == pytest.approx(33.0, abs=0.1)
