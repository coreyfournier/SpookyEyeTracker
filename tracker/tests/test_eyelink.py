"""EyeLink against a fake eye speaking the firmware's UDP protocol on localhost."""
import json
import socket
import threading
import time

import pytest

from eyetracker.config import firmware_version
from eyetracker.eyelink import EyeLink


class FakeEye:
    def __init__(self, ack=True):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.ack = ack
        self.received = []
        self.ver = 0
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            msg = json.loads(data)
            self.received.append(msg)
            if msg["t"] == "cfg" and self.ack:
                self.ver = msg["ver"]
                self.sock.sendto(json.dumps({"t": "ack", "ver": msg["ver"]}).encode(), addr)
            elif msg["t"] == "ping":
                self.sock.sendto(json.dumps({"t": "status", "id": "eye1", "ver": self.ver, "state": "idle", "act": "wander",
                                             "fw": "abc1234", "built": "2026-11-01", "board": "featheresp32",
                                             "pan": 0, "tilt": 0, "rssi": -50, "up": 1}).encode(), addr)

    def close(self):
        self._stop.set()
        self.sock.close()


@pytest.fixture
def fake_eye():
    eye = FakeEye()
    yield eye
    eye.close()


@pytest.fixture
def linked(store, fake_eye):
    eye = store.eye("eye1")
    eye.update(ip="127.0.0.1", port=fake_eye.port)
    store.replace_item("eyes", eye, save=False)
    link = EyeLink(store)
    link.start()
    return link, store.eye("eye1")


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_push_config_is_acknowledged(linked, fake_eye):
    link, eye = linked
    assert link.push_config(eye)
    cfg = next(m for m in fake_eye.received if m["t"] == "cfg")
    assert cfg["ver"] == firmware_version(eye["firmware"])
    assert cfg["servos"] == eye["firmware"]["servos"]


def test_status_goes_online_and_in_sync(linked):
    link, eye = linked
    link.push_config(eye)
    assert wait_for(lambda: link.status(eye)["online"])
    assert wait_for(lambda: link.status(eye)["config_in_sync"])
    assert link.status(eye)["activity"] == "wander"
    assert link.status(eye)["fw"] == {"version": "abc1234", "built": "2026-11-01", "board": "featheresp32", "ota": False}


def test_push_without_ack_fails(store):
    silent = FakeEye(ack=False)
    try:
        eye = dict(store.eye("eye1"), ip="127.0.0.1", port=silent.port)
        store.replace_item("eyes", eye, save=False)
        link = EyeLink(store)
        link.start()
        assert not link.push_config(eye, retries=2, timeout=0.2)
    finally:
        silent.close()


def test_look_and_manual_messages(linked, fake_eye):
    link, eye = linked
    link.look(eye, True, 12.345, -3.21, new=True)
    link.manual(eye, pan=5, raw=[1500, 0, 0, 0])
    link.release(eye)
    link.identify(eye, True, (0, 255, 255), hold_s=30)
    assert wait_for(lambda: len([m for m in fake_eye.received if m["t"] != "ping"]) >= 4)
    msgs = [m for m in fake_eye.received if m["t"] != "ping"]
    assert msgs[0] == {"t": "look", "tgt": 1, "pan": 12.35, "tilt": -3.21, "new": 1}
    assert msgs[1]["t"] == "manual" and msgs[1]["raw"] == [1500, 0, 0, 0]
    assert msgs[2] == {"t": "release"}
    assert msgs[3] == {"t": "identify", "on": 1, "rgb": [0, 255, 255], "hold_s": 30}


def test_sent_remembers_the_last_command_of_each_kind(linked):
    link, eye = linked
    link.look(eye, True, 10.0, -3.0, new=True)
    link.manual(eye, pan=4.0, tilt=1.0, lid=0.5)
    link.look(eye, False)
    sent = link.sent("eye1")
    assert set(sent) == {"look", "manual"}            # pings and config pushes aren't replayed
    assert sent["look"]["tgt"] == 0                   # the latest look wins
    assert sent["manual"]["lid"] == 0.5 and 0 <= sent["manual"]["age"] < 1
    assert link.sent("nobody") == {}
