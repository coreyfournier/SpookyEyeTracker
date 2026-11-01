import pytest

from eyetracker import version
from eyetracker.version import firmware_status, latest_firmware_version


@pytest.mark.parametrize("reported,latest,expected", [
    ("abc1234", "abc1234", "current"),
    ("abc1234-dirty", "abc1234", "dirty"),
    ("0000000", "abc1234", "outdated"),
    ("0000000-dirty", "abc1234", "outdated"),
    (None, "abc1234", "unknown"),           # firmware from before versioning
    ("unknown", "abc1234", "unknown"),      # built outside a git checkout
    ("abc1234", None, "unknown"),           # tracker can't tell what's latest
])
def test_firmware_status(reported, latest, expected):
    assert firmware_status(reported, latest) == expected


def test_latest_prefers_env_and_trims(monkeypatch):
    monkeypatch.setenv("EYETRACKER_FIRMWARE_VERSION", "abc1234def5678")
    assert latest_firmware_version() == "abc1234"


def test_latest_from_git_is_cached(monkeypatch):
    monkeypatch.delenv("EYETRACKER_FIRMWARE_VERSION", raising=False)
    monkeypatch.setattr(version, "_cache", (0.0, None))
    calls = []
    monkeypatch.setattr(version, "_git", lambda *a: calls.append(a) or "fedcba9876543210")
    assert latest_firmware_version() == "fedcba9"
    assert latest_firmware_version() == "fedcba9"
    assert len(calls) == 1
    assert calls[0] == ("log", "-1", "--format=%H", "--", "firmware")


def test_latest_without_git_is_none(monkeypatch):
    monkeypatch.delenv("EYETRACKER_FIRMWARE_VERSION", raising=False)
    monkeypatch.setattr(version, "_cache", (0.0, None))
    monkeypatch.setattr(version, "_git", lambda *a: "")
    assert latest_firmware_version() is None
