import copy

import pytest
import yaml

from eyetracker.config import (MAX_CAMERAS, ConfigError, ConfigStore, camera_ip, ensure_config,
                               firmware_version, redact, rtsp_url, validate)


def test_bundled_config_is_valid(cfg_dict):
    assert validate(cfg_dict) == []


def test_zero_one_or_two_cameras_are_allowed(cfg_dict):
    for n in range(MAX_CAMERAS + 1):
        cfg = copy.deepcopy(cfg_dict)
        cfg["cameras"] = cfg["cameras"][:n]
        assert validate(cfg) == [], n


def test_more_than_two_cameras_rejected(cfg_dict):
    extra = dict(cfg_dict["cameras"][0], id="third")
    cfg_dict["cameras"].append(extra)
    assert any("at most 2 cameras" in e for e in validate(cfg_dict))


def test_duplicate_ids_rejected(cfg_dict):
    cfg_dict["cameras"][1]["id"] = cfg_dict["cameras"][0]["id"]
    assert any("duplicate camera" in e for e in validate(cfg_dict))


def test_camera_needs_an_address(cfg_dict):
    cam = cfg_dict["cameras"][0]
    cam.pop("ip_env")
    cam.pop("ip", None)
    assert any("set ip or ip_env" in e for e in validate(cfg_dict))


def test_store_refuses_invalid_update_and_keeps_old(store, cfg_dict):
    bad = store.get()
    bad["cameras"].append(dict(bad["cameras"][0], id="third"))
    with pytest.raises(ConfigError):
        store.update(bad, save=True)
    assert len(store.get()["cameras"]) == 2
    assert len(yaml.safe_load(store.path.read_text())["cameras"]) == 2


def test_invalid_file_fails_to_load(tmp_path, cfg_dict):
    cfg_dict["cameras"].append(dict(cfg_dict["cameras"][0], id="third"))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg_dict))
    with pytest.raises(ConfigError):
        ConfigStore(path)


def test_old_config_gets_sclera_brightness_from_brightness(tmp_path, cfg_dict):
    iris = cfg_dict["eyes"][0]["firmware"]["behaviors"]["iris"]
    del iris["sclera_brightness"]
    iris["brightness"] = 187
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg_dict, sort_keys=False))
    iris = ConfigStore(path).eye(cfg_dict["eyes"][0]["id"])["firmware"]["behaviors"]["iris"]
    assert iris["sclera_brightness"] == 187        # looks the same as before the split
    keys = list(iris)
    assert keys.index("sclera_brightness") == keys.index("brightness") + 1


def test_save_roundtrip_and_remove(store):
    eye = store.eye("eye1")
    eye["name"] = "Porch"
    store.replace_item("eyes", eye, save=True)
    assert ConfigStore(store.path).eye("eye1")["name"] == "Porch"
    assert store.remove_item("cameras", "left_to_right", save=True)
    assert not store.remove_item("cameras", "nope", save=True)
    assert [c["id"] for c in ConfigStore(store.path).get()["cameras"]] == ["right_to_left"]


def test_revision_bumps_on_update(store):
    rev = store.revision
    store.update(store.get(), save=False)
    assert store.revision == rev + 1


def test_ensure_config_copies_default(tmp_path):
    path = tmp_path / "sub" / "config.yaml"
    ensure_config(path)
    assert validate(yaml.safe_load(path.read_text())) == []


def test_camera_ip_prefers_env(monkeypatch):
    monkeypatch.setenv("TEST_CAM_IP", "10.0.0.9")
    assert camera_ip({"ip_env": "TEST_CAM_IP", "ip": "1.1.1.1"}) == "10.0.0.9"
    monkeypatch.delenv("TEST_CAM_IP")
    assert camera_ip({"ip_env": "TEST_CAM_IP", "ip": "1.1.1.1"}) == "1.1.1.1"
    assert camera_ip({"ip": "1.1.1.1", "ip_env": ""}) == "1.1.1.1"


def test_rtsp_url_escapes_and_redacts(monkeypatch):
    monkeypatch.setenv("CAMERA_USERNAME", "admin")
    monkeypatch.setenv("CAMERA_PASSWORD", "'p@ss:word")
    creds = {"username_env": "CAMERA_USERNAME", "password_env": "CAMERA_PASSWORD"}
    url = rtsp_url({"ip": "192.168.4.61", "channel": 102}, creds)
    assert url == "rtsp://admin:%27p%40ss%3Aword@192.168.4.61:554/Streaming/Channels/102"
    assert redact(url) == "rtsp://admin:***@192.168.4.61:554/Streaming/Channels/102"


def test_firmware_version_is_stable_and_order_independent():
    a = {"servos": {"pan": {"center": 1500}}, "motion": {"max_speed": 400}}
    b = {"motion": {"max_speed": 400}, "servos": {"pan": {"center": 1500}}}
    assert firmware_version(a) == firmware_version(b)
    assert firmware_version(a) != firmware_version({**a, "motion": {"max_speed": 401}})
