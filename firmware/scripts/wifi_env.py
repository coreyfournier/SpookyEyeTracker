# PlatformIO pre-build script: injects WiFi credentials and the OTA password from the
# environment (or the project .env) so they never live in the repo.
#
#   ENV_WIFI_SSID / ENV_WIFI_PW   WiFi network (environment variables)
#   EYE_OTA_PASSWORD              password for over-the-air updates (environment or ../.env);
#                                 without it the firmware has no update endpoint
import os
from pathlib import Path

Import("env")  # noqa: F821  (provided by PlatformIO/SCons)


def dotenv(name: str) -> str | None:
    """Read one key from the project's .env (handles "double quoted" values)."""
    path = Path(env.subst("$PROJECT_DIR")).parent / ".env"  # noqa: F821
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            return value
    return None


ssid = os.environ.get("ENV_WIFI_SSID")
password = os.environ.get("ENV_WIFI_PW")
if not ssid or password is None:
    print("*** wifi_env.py: ENV_WIFI_SSID / ENV_WIFI_PW are not set - the eye will not join WiFi ***")
    ssid, password = ssid or "", password or ""

ota_password = os.environ.get("EYE_OTA_PASSWORD") or dotenv("EYE_OTA_PASSWORD") or ""
if not ota_password:
    print("*** wifi_env.py: EYE_OTA_PASSWORD not set - over-the-air updates are disabled ***")

env.Append(CPPDEFINES=[  # noqa: F821
    ("WIFI_SSID", env.StringifyMacro(ssid)),  # noqa: F821
    ("WIFI_PASS", env.StringifyMacro(password)),  # noqa: F821
    ("OTA_PASSWORD", env.StringifyMacro(ota_password)),  # noqa: F821
])
