# PlatformIO pre-build script: stamps the firmware with its version so the tracker can
# tell whether an eye is running the latest code.
#
#   FW_VERSION  first 7 chars of the last commit that touched firmware/, plus "-dirty" if
#               firmware/ has uncommitted changes ("unknown" outside a git checkout)
#   FW_BUILT    UTC build date (YYYY-MM-DD)
#   FW_BOARD    PlatformIO board id (e.g. heltec_wifi_kit_32_v2, featheresp32)
import datetime
import subprocess

Import("env")  # noqa: F821  (provided by PlatformIO/SCons)

fw_dir = env.subst("$PROJECT_DIR")  # noqa: F821


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=fw_dir, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


sha = git("log", "-1", "--format=%H", "--", ".")[:7]
version = sha or "unknown"
if sha and git("status", "--porcelain", "--", "."):
    version += "-dirty"
built = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
board = env.BoardConfig().id  # noqa: F821

print(f"version.py: firmware {version} built {built} for {board}")
env.Append(CPPDEFINES=[  # noqa: F821
    ("FW_VERSION", env.StringifyMacro(version)),  # noqa: F821
    ("FW_BUILT", env.StringifyMacro(built)),  # noqa: F821
    ("FW_BOARD", env.StringifyMacro(board)),  # noqa: F821
])
