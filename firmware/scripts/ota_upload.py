"""Upload firmware to an eye over WiFi.

    pio run -e eye1_ota -t upload                          # builds eye1, uploads to its IP
    pio run -e eye1_ota -t upload --upload-port 192.168.2.143
    python scripts/ota_upload.py --eye eye1 .pio/build/eye1/firmware.bin

The eye's IP comes from --upload-port / --ip, else from the running tracker
(http://localhost:8080/api/config). The password is EYE_OTA_PASSWORD (environment or ../.env).
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tracker"))
from eyetracker.ota import OtaError, detect_board, upload  # noqa: E402  (stdlib-only module)


def dotenv(name):
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                value = value.strip()
                return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value
    return None


def eye_ip_from_tracker(eye_id, url):
    try:
        with urllib.request.urlopen(url + "/api/config", timeout=3) as r:
            for eye in json.load(r)["eyes"]:
                if eye["id"] == eye_id:
                    return eye["ip"]
    except OSError:
        return None
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eye", help="eye id, used to look up its IP in the tracker")
    ap.add_argument("--ip", default="", help="eye IP (overrides the lookup)")
    ap.add_argument("--tracker", default="http://localhost:8080")
    ap.add_argument("firmware", help="path to firmware.bin")
    args = ap.parse_args()

    ip = args.ip.strip() or (args.eye and eye_ip_from_tracker(args.eye, args.tracker))
    if not ip:
        sys.exit(f"Can't find the IP for '{args.eye}': start the tracker or pass --upload-port <ip>")
    password = os.environ.get("EYE_OTA_PASSWORD") or dotenv("EYE_OTA_PASSWORD")
    if not password:
        sys.exit("EYE_OTA_PASSWORD is not set (add it to .env)")

    image = Path(args.firmware).read_bytes()
    try:
        print(f"Uploading {len(image) // 1024} KB ({detect_board(image)}) to {args.eye or ''} at {ip} ...", flush=True)
        print("Eye says:", upload(ip, image, password))
    except OtaError as exc:
        sys.exit(f"OTA failed: {exc}")


if __name__ == "__main__":
    main()
