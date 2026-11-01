import copy

import pytest
import yaml

from eyetracker.config import BUNDLED_CONFIG, ConfigStore


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
