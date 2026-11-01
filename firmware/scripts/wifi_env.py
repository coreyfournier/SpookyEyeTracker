# PlatformIO pre-build script: injects WiFi credentials from environment variables
# so they never live in the repo.
import os

Import("env")  # noqa: F821  (provided by PlatformIO/SCons)

ssid = os.environ.get("ENV_WIFI_SSID")
password = os.environ.get("ENV_WIFI_PW")

if not ssid or password is None:
    print("*** wifi_env.py: ENV_WIFI_SSID / ENV_WIFI_PW are not set - the eye will not join WiFi ***")
    ssid, password = ssid or "", password or ""

env.Append(CPPDEFINES=[  # noqa: F821
    ("WIFI_SSID", env.StringifyMacro(ssid)),  # noqa: F821
    ("WIFI_PASS", env.StringifyMacro(password)),  # noqa: F821
])
