"""Which firmware version is current, and whether an eye is running it.

Versions are the first 7 chars of the last commit that touched firmware/ (see
firmware/scripts/version.py), optionally with "-dirty". The latest version comes from
$EYETRACKER_FIRMWARE_VERSION (baked into the Docker image by CI), else from git.
"""
from __future__ import annotations

import os
import subprocess
import time

from .config import PROJECT_DIR

CACHE_S = 30.0
_cache: tuple[float, str | None] = (0.0, None)


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=PROJECT_DIR, capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def latest_firmware_version() -> str | None:
    """Latest firmware commit (7 chars), or None if it can't be determined."""
    global _cache
    env = os.environ.get("EYETRACKER_FIRMWARE_VERSION", "").strip()
    if env:
        return env[:7]
    now = time.time()
    if now - _cache[0] < CACHE_S:
        return _cache[1]
    sha = _git("log", "-1", "--format=%H", "--", "firmware")[:7] or None
    _cache = (now, sha)
    return sha


def firmware_status(reported: str | None, latest: str | None) -> str:
    """current | outdated | dirty | unknown

    unknown  - the eye didn't report a version (firmware older than versioning) or
               the latest version can't be determined
    dirty    - built from uncommitted changes on top of the latest commit
    outdated - built from an older (or different) commit
    """
    if not reported or reported == "unknown" or not latest:
        return "unknown"
    base, _, suffix = reported.partition("-")
    if base != latest:
        return "outdated"
    return "dirty" if suffix == "dirty" else "current"
