import copy

import pytest
import yaml
from fastapi.testclient import TestClient

from eyetracker.calib import Calibrator
from eyetracker.camcal import CameraCalibration
from eyetracker.camera import CameraManager
from eyetracker.config import BUNDLED_CONFIG, ConfigStore
from eyetracker.director import Director
from eyetracker.web import create_app
from eyetracker.world import World


@pytest.fixture
def cfg_dict() -> dict:
    return yaml.safe_load(BUNDLED_CONFIG.read_text(encoding="utf-8"))


@pytest.fixture
def make_store(tmp_path):
    """Write a config dict to a temp dir and return a ConfigStore for it."""
    def make(cfg: dict) -> ConfigStore:
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(copy.deepcopy(cfg)), encoding="utf-8")
        return ConfigStore(path)
    return make


@pytest.fixture
def store(make_store, cfg_dict) -> ConfigStore:
    return make_store(cfg_dict)


class FakeLink:
    def __init__(self):
        self.pushed, self.manuals, self.identifies = [], [], []

    def push_config(self, eye, **_):
        self.pushed.append(eye["id"])
        return True

    def status(self, eye):
        return {"online": True, "state": "idle", "config_in_sync": True,
                "fw": {"version": "1111111", "built": "2026-11-01", "board": "featheresp32", "ota": True}}

    def manual(self, eye, **kw):
        self.manuals.append(kw)

    def release(self, eye):
        pass

    def identify(self, eye, on, rgb, hold_s=60):
        self.identifies.append((eye["id"], on, list(rgb), hold_s))

    def look(self, *a, **kw):
        pass


@pytest.fixture
def app(store):
    world = World(store)
    link = FakeLink()
    cameras = CameraManager(store, world, None, active=False)
    client = TestClient(create_app(store, world, link, Director(store, world, link), cameras,
                                   Calibrator(store, world), CameraCalibration(store, cameras)))
    client.link = link
    client.cameras = cameras
    client.app_world = world
    return client
