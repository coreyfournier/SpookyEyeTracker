"""Run with:  python -m eyetracker [--config path] [--no-cameras]

The config path defaults to $EYETRACKER_CONFIG, else tracker-data/config.yaml. If the file
doesn't exist yet (first run, or a fresh Docker volume) config.default.yaml is copied there.
"""
from __future__ import annotations

import argparse
import logging
import threading

import uvicorn

from .calib import Calibrator
from .camcal import CameraCalibration
from .camera import CameraManager
from .config import DEFAULT_CONFIG, ConfigStore, ensure_config
from .director import Director
from .eyelink import EyeLink
from .web import create_app
from .world import World

log = logging.getLogger(__name__)


def model_factory(store: ConfigStore):
    """Builds a YOLO model per camera; ultralytics is imported only when a camera starts."""
    lock = threading.Lock()

    def make():
        from ultralytics import YOLO
        with lock:  # first call downloads the weights; parallel downloads corrupt the file
            return YOLO(store.section("detection")["model"])

    return make


def main():
    ap = argparse.ArgumentParser(description="Camera person tracking -> animatronic eyes")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--no-cameras", action="store_true", help="UI + eye link only (calibrate servos)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store = ConfigStore(ensure_config(args.config))
    log.info("config: %s", store.path)
    world = World(store)
    link = EyeLink(store)
    link.start()
    director = Director(store, world, link)
    director.start()

    cameras = CameraManager(store, world, model_factory(store), active=not args.no_cameras)
    cameras.sync()
    log.info("cameras: %s", ", ".join(cameras.workers) or "none")

    camcal = CameraCalibration(store, cameras)
    camcal.start_polling()

    web = store.section("web")
    log.info("UI: http://localhost:%s  (phone: /calibrate, /camcal)", web["port"])
    app = create_app(store, world, link, director, cameras, Calibrator(store, world), camcal)
    uvicorn.run(app, host=web["host"], port=web["port"], log_level="warning")


if __name__ == "__main__":
    main()
