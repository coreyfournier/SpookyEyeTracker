"""ONVIF client against a fake camera, plus the camera types around it (config, stream source, API)."""
import base64
import hashlib
import threading
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from eyetracker import onvif
from eyetracker.camera import stream_source
from eyetracker.config import camera_login, custom_url, redact, usb_device, validate

USER, PASSWORD = "onvif-user", "s3cret:pw"
CREDS = {"username_env": "CAMERA_USERNAME", "password_env": "CAMERA_PASSWORD"}

PROFILES = """<trt:GetProfilesResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
<trt:Profiles token="Profile_1" fixed="true"><tt:Name>mainStream</tt:Name><tt:VideoEncoderConfiguration token="V1">
  <tt:Name>v1</tt:Name><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>2560</tt:Width><tt:Height>1440</tt:Height></tt:Resolution>
  <tt:RateControl><tt:FrameRateLimit>20</tt:FrameRateLimit></tt:RateControl></tt:VideoEncoderConfiguration></trt:Profiles>
<trt:Profiles token="Profile_2" fixed="true"><tt:Name>subStream</tt:Name><tt:VideoEncoderConfiguration token="V2">
  <tt:Name>v2</tt:Name><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>640</tt:Width><tt:Height>360</tt:Height></tt:Resolution>
  <tt:RateControl><tt:FrameRateLimit>15</tt:FrameRateLimit></tt:RateControl></tt:VideoEncoderConfiguration></trt:Profiles>
</trt:GetProfilesResponse>"""


def envelope(body):
    return f'<?xml version="1.0"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>{body}</s:Body></s:Envelope>'


class FakeCamera(BaseHTTPRequestHandler):
    """Answers the ONVIF calls the client makes, and checks the WS-Security digest like a camera."""
    calls = []

    def log_message(self, *_):
        pass

    def reply(self, code, body):
        data = envelope(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/soap+xml")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorised(self, root) -> bool:
        tok = onvif._find(root, "UsernameToken")
        if tok is None or onvif._text(tok, "Username") != USER:
            return False
        nonce = base64.b64decode(onvif._text(tok, "Nonce"))
        created = onvif._text(tok, "Created")
        want = base64.b64encode(hashlib.sha1(nonce + created.encode() + PASSWORD.encode()).digest()).decode()
        return onvif._text(tok, "Password") == want

    def do_POST(self):
        root = ET.fromstring(self.rfile.read(int(self.headers["Content-Length"])))
        body = onvif._find(root, "Body")[0]
        op = body.tag.rsplit("}", 1)[-1]
        FakeCamera.calls.append((self.path, op))
        port = self.server.server_address[1]
        if op == "GetSystemDateAndTime":
            return self.reply(200, "<tds:GetSystemDateAndTimeResponse xmlns:tds='x' xmlns:tt='y'><tds:SystemDateAndTime>"
                                   "<tt:UTCDateTime><tt:Time><tt:Hour>12</tt:Hour><tt:Minute>0</tt:Minute><tt:Second>0</tt:Second>"
                                   "</tt:Time><tt:Date><tt:Year>2026</tt:Year><tt:Month>11</tt:Month><tt:Day>3</tt:Day></tt:Date>"
                                   "</tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>")
        if not self.authorised(root):
            return self.reply(400, "<s:Fault><s:Reason><s:Text>Sender not Authorized</s:Text></s:Reason></s:Fault>")
        if op == "GetCapabilities":
            # reports an address we can't reach (as cameras behind NAT do); the client keeps only the path
            return self.reply(200, "<x:GetCapabilitiesResponse xmlns:x='x'><x:Capabilities><x:Media>"
                                   "<x:XAddr>http://10.99.99.99/onvif/Media</x:XAddr></x:Media></x:Capabilities>"
                                   "</x:GetCapabilitiesResponse>")
        if op == "GetProfiles":
            return self.reply(200, PROFILES)
        if op == "GetStreamUri":
            token = onvif._text(body, "ProfileToken")
            return self.reply(200, f"<x:GetStreamUriResponse xmlns:x='x'><x:MediaUri><x:Uri>"
                                   f"rtsp://127.0.0.1:554/Streaming/Channels/{101 if token == 'Profile_1' else 102}"
                                   f"</x:Uri></x:MediaUri></x:GetStreamUriResponse>")
        self.reply(400, "<s:Fault/>")

    def do_GET(self):
        self.send_error(404)


class NoOnvif(FakeCamera):
    """A camera with ONVIF switched off: every ONVIF address is a 404."""
    def do_POST(self):
        self.send_error(404)


def test_onvif_switched_off_is_explained():
    srv = HTTPServer(("127.0.0.1", 0), NoOnvif)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(onvif.OnvifError, match="has no ONVIF service.*Integration Protocol"):
            onvif.Camera("127.0.0.1", srv.server_address[1], USER, PASSWORD).profiles()
    finally:
        srv.shutdown()


@pytest.fixture
def fake_camera():
    srv = HTTPServer(("127.0.0.1", 0), FakeCamera)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeCamera.calls = []
    yield srv.server_address[1]
    srv.shutdown()


def test_profiles_and_stream_uri(fake_camera):
    cam = onvif.Camera("127.0.0.1", fake_camera, USER, PASSWORD)
    profs = cam.profiles()
    assert [p["token"] for p in profs] == ["Profile_1", "Profile_2"]
    assert profs[0] == {"token": "Profile_1", "name": "mainStream", "encoding": "H264", "width": 2560,
                        "height": 1440, "fps": 20.0}
    # empty = highest resolution; the login is added to the URI so OpenCV can open it
    assert cam.stream_uri() == "rtsp://onvif-user:s3cret%3Apw@127.0.0.1:554/Streaming/Channels/101"
    assert cam.stream_uri("subStream").endswith("/Channels/102")          # by name
    assert cam.stream_uri("Profile_2").endswith("/Channels/102")          # by token
    # the media service is reached on the camera's own address, not the one it reported
    assert ("/onvif/Media", "GetProfiles") in FakeCamera.calls


def test_unknown_profile_and_bad_login(fake_camera):
    with pytest.raises(onvif.OnvifError, match="no profile 'nope'.*Profile_1, Profile_2"):
        onvif.Camera("127.0.0.1", fake_camera, USER, PASSWORD).stream_uri("nope")
    with pytest.raises(onvif.OnvifError, match="refused the ONVIF login.*Hikvision"):
        onvif.Camera("127.0.0.1", fake_camera, USER, "wrong").profiles()


def test_unreachable_camera_says_so():
    with pytest.raises(onvif.OnvifError, match="didn't answer ONVIF"):
        onvif.Camera("127.0.0.1", 1, USER, PASSWORD, timeout=1).profiles()


def test_discovery_reply_is_parsed():
    reply = b"""<?xml version="1.0"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"><s:Body><d:ProbeMatches><d:ProbeMatch>
      <d:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/name/HIKVISION
        onvif://www.onvif.org/hardware/DS-2CD2143G2-I onvif://www.onvif.org/location/city/hangzhou</d:Scopes>
      <d:XAddrs>http://192.168.4.61:8000/onvif/device_service http://[fe80::1]/onvif/device_service</d:XAddrs>
      </d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>"""
    assert onvif.parse_probe_match(reply) == {"ip": "192.168.4.61", "port": 8000, "name": "HIKVISION",
                                              "hardware": "DS-2CD2143G2-I",
                                              "xaddr": "http://192.168.4.61:8000/onvif/device_service"}
    assert onvif.parse_probe_match(b"not xml") is None
    # a Windows PC / NAS answering the probe isn't a camera
    nas = b"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:d="x"><s:Body><d:ProbeMatches>
      <d:ProbeMatch><d:Types>wsdp:Device pub:Computer</d:Types><d:XAddrs>http://NAS:5357/c86b</d:XAddrs>
      </d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>"""
    assert onvif.parse_probe_match(nas) is None


# ---------- camera types ----------
def cam_of(kind, **kw):
    return {"id": "c", "type": kind, "position": [0, 0, 3], "heading": 0, "pitch": -15, "hfov": 90, **kw}


def test_validation_per_type(cfg_dict):
    def errors(cam):
        cfg_dict["cameras"] = [cam]
        return validate(cfg_dict)
    assert errors(cam_of("onvif", ip="10.0.0.5")) == []
    assert errors(cam_of("rtsp", url="rtsp://{user}:{password}@{ip}/s1")) == []
    assert errors(cam_of("usb", device=0)) == []
    assert any("set ip" in e for e in errors(cam_of("onvif")))
    assert any("url must be" in e for e in errors(cam_of("rtsp", url="192.168.1.5/stream")))
    assert any("set device" in e for e in errors(cam_of("usb", device="")))
    assert any("type must be one of" in e for e in errors(cam_of("axis", ip="10.0.0.5")))


def test_old_cameras_become_hikvision(make_store, cfg_dict):
    for c in cfg_dict["cameras"]:
        del c["type"]
    cams = make_store(cfg_dict).get()["cameras"]
    for c in cams:
        assert c["type"] == "hikvision" and list(c).index("type") == list(c).index("id") + 1


def test_login_url_and_device(monkeypatch):
    monkeypatch.setenv("CAMERA_USERNAME", "admin")
    monkeypatch.setenv("CAMERA_PASSWORD", "shared")
    monkeypatch.setenv("ONVIF_USER", USER)
    monkeypatch.setenv("ONVIF_PW", PASSWORD)
    assert camera_login({}, CREDS) == ("admin", "shared")
    assert camera_login({"username_env": "ONVIF_USER", "password_env": "ONVIF_PW"}, CREDS) == (USER, PASSWORD)
    url = custom_url({"url": "rtsp://{user}:{password}@{ip}:554/live", "ip": "10.0.0.7",
                      "password_env": "ONVIF_PW"}, CREDS)
    assert url == "rtsp://admin:s3cret%3Apw@10.0.0.7:554/live"
    assert redact(url, PASSWORD) == "rtsp://admin:***@10.0.0.7:554/live"
    assert usb_device({"device": 2}) == 2 and usb_device({"device": "1"}) == 1
    assert usb_device({"device": "/dev/video2"}) == "/dev/video2"


def test_stream_source_per_type(fake_camera, monkeypatch):
    monkeypatch.setenv("CAMERA_USERNAME", USER)
    monkeypatch.setenv("CAMERA_PASSWORD", PASSWORD)
    src, shown = stream_source(cam_of("onvif", ip="127.0.0.1", onvif_port=fake_camera, profile="Profile_2"), CREDS)
    assert src.endswith("/Channels/102") and PASSWORD not in shown and "***" in shown
    src, shown = stream_source(cam_of("hikvision", ip="10.0.0.9", channel=101), CREDS)
    assert src.startswith("rtsp://onvif-user:") and src.endswith("10.0.0.9:554/Streaming/Channels/101")
    assert stream_source(cam_of("usb", device=1), CREDS) == (1, "USB camera 1")
    with pytest.raises(onvif.OnvifError):
        stream_source(cam_of("onvif", ip="127.0.0.1", onvif_port=fake_camera, profile="missing"), CREDS)


# ---------- API ----------
def test_api_profiles_discover_and_usb(app, fake_camera, monkeypatch):
    client = app
    monkeypatch.setenv("CAMERA_USERNAME", USER)
    monkeypatch.setenv("CAMERA_PASSWORD", PASSWORD)
    r = client.post("/api/onvif/profiles", json={"ip": "127.0.0.1", "onvif_port": fake_camera})
    assert r.status_code == 200 and [p["name"] for p in r.json()["profiles"]] == ["mainStream", "subStream"]
    monkeypatch.setenv("CAMERA_PASSWORD", "wrong")
    r = client.post("/api/onvif/profiles", json={"ip": "127.0.0.1", "onvif_port": fake_camera})
    assert r.status_code == 502 and "refused the ONVIF login" in r.json()["detail"]
    assert client.post("/api/onvif/profiles", json={}).status_code == 400

    monkeypatch.setattr(onvif, "discover", lambda: [{"ip": "10.0.0.5", "port": 80, "name": "x", "hardware": "y",
                                                     "xaddr": "http://10.0.0.5/onvif/device_service"}])
    assert client.get("/api/onvif/discover").json()["cameras"][0]["ip"] == "10.0.0.5"

    import eyetracker.camera as camera
    seen = {}
    def fake_list(skip=()):
        seen["skip"] = set(skip)
        return [{"device": 0, "width": 1280, "height": 720, "in_use": False}]
    monkeypatch.setattr(camera, "list_usb_cameras", fake_list)
    assert client.get("/api/usb/devices").json()["devices"][0]["width"] == 1280
    assert seen["skip"] == set()


def test_api_adds_each_camera_type(app):
    client = app
    for c in list(client.get("/api/config").json()["cameras"]):
        assert client.delete(f"/api/cameras/{c['id']}").status_code == 200
    assert client.post("/api/cameras", json=cam_of("usb", id="webcam", device=0, width=1280, height=720)).status_code == 200
    assert client.post("/api/cameras", json=cam_of("onvif", id="porch", ip="10.0.0.5", onvif_port=80,
                                                   profile="")).status_code == 200
    r = client.post("/api/cameras", json=cam_of("rtsp", id="third", url="rtsp://x/y"))
    assert r.status_code == 400 and "at most 2 cameras" in r.text    # still capped at two
    types = {c["id"]: c["type"] for c in client.get("/api/config").json()["cameras"]}
    assert types == {"webcam": "usb", "porch": "onvif"}
