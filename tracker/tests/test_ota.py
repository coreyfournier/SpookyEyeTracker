import base64
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from eyetracker.ota import OtaError, detect_board, upload

FEATHER_IMG = bytes([0xE9]) + b"\0" * 64 + b"featheresp32\0" + b"\x01" * 2000
HELTEC_IMG = bytes([0xE9]) + b"\0" * 64 + b"heltec_wifi_kit_32_v2\0" + b"\x02" * 2000


def test_detect_board():
    assert detect_board(FEATHER_IMG) == "featheresp32"
    assert detect_board(HELTEC_IMG) == "heltec_wifi_kit_32_v2"


@pytest.mark.parametrize("image", [b"", b"PK\x03\x04 zip file", bytes([0xE9]) + b"no board id here"])
def test_detect_board_rejects_non_eye_images(image):
    with pytest.raises(OtaError):
        detect_board(image)


class FakeEyeUpdateServer:
    """Mimics firmware/src/ota.cpp: Basic auth eye:<password>, ?board= must match."""

    def __init__(self, board="featheresp32", password="secret"):
        self.board, self.password, self.received = board, password, None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                expected = "Basic " + base64.b64encode(f"eye:{outer.password}".encode()).decode()
                url = urlparse(self.path)
                if url.path != "/update":
                    return self._reply(404, b"not found")
                if self.headers.get("Authorization") != expected:
                    return self._reply(401, b"")
                if parse_qs(url.query).get("board") != [outer.board]:
                    return self._reply(409, b"firmware is for a different board")
                outer.received = body
                self._reply(200, b"ok, rebooting")

            def _reply(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def eye_server():
    s = FakeEyeUpdateServer()
    yield s
    s.close()


def test_upload_sends_multipart_image(eye_server):
    assert upload("127.0.0.1", FEATHER_IMG, "secret", port=eye_server.port, timeout=5) == "ok, rebooting"
    assert FEATHER_IMG in eye_server.received
    assert b'filename="firmware.bin"' in eye_server.received


def test_wrong_password(eye_server):
    with pytest.raises(OtaError, match="password"):
        upload("127.0.0.1", FEATHER_IMG, "nope", port=eye_server.port, timeout=5)


def test_wrong_board(eye_server):
    with pytest.raises(OtaError, match="409"):
        upload("127.0.0.1", HELTEC_IMG, "secret", port=eye_server.port, timeout=5)


def test_unreachable_eye():
    with pytest.raises(OtaError, match="couldn't reach"):
        upload("127.0.0.1", FEATHER_IMG, "secret", port=1, timeout=2)
