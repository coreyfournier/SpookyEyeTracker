"""Minimal ONVIF client: find cameras on the network and ask one for its RTSP stream address.

ONVIF doesn't carry the video itself - a Profile S camera still streams RTSP. We only need three
SOAP calls (the time, the media service address, the stream profiles and their RTSP URIs) and a
WS-Discovery probe, so this talks SOAP directly with the standard library instead of pulling in
a full SOAP stack.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import os
import socket
import uuid
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
PW_DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
B64 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
DEVICE_NS = "http://www.onvif.org/ver10/device/wsdl"
MEDIA_NS = "http://www.onvif.org/ver10/media/wsdl"
SCHEMA_NS = "http://www.onvif.org/ver10/schema"
DISCOVERY_ADDR = ("239.255.255.250", 3702)


class OnvifError(RuntimeError):
    pass


def _find(el, name):
    """First descendant with this local name (ONVIF responses use varying namespace prefixes)."""
    return next((e for e in el.iter() if e.tag.rsplit("}", 1)[-1] == name), None)


def _findall(el, name):
    return [e for e in el.iter() if e.tag.rsplit("}", 1)[-1] == name]


def _text(el, name, default=""):
    e = _find(el, name) if el is not None else None
    return e.text.strip() if e is not None and e.text else default


class Camera:
    """One ONVIF camera: http://ip:port/onvif/device_service, WS-Security digest login."""

    def __init__(self, ip: str, port: int = 80, user: str = "", password: str = "", timeout: float = 5.0):
        self.ip, self.port, self.user, self.password, self.timeout = ip, int(port), user, password, timeout
        self.device_url = f"http://{ip}:{self.port}/onvif/device_service"
        self._clock_offset = None   # camera clock - ours; digest login fails if they differ much

    # ---------- SOAP ----------
    def _security(self) -> str:
        if not self.user:
            return ""
        if self._clock_offset is None:
            self._clock_offset = self._camera_clock_offset()
        created = (dt.datetime.now(dt.timezone.utc) + self._clock_offset).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        nonce = os.urandom(16)
        digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + self.password.encode()).digest()).decode()
        return (f'<s:Header><wsse:Security xmlns:wsse="{WSSE}" xmlns:wsu="{WSU}" s:mustUnderstand="1">'
                f"<wsse:UsernameToken><wsse:Username>{escape(self.user)}</wsse:Username>"
                f'<wsse:Password Type="{PW_DIGEST}">{digest}</wsse:Password>'
                f'<wsse:Nonce EncodingType="{B64}">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
                f"<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header>")

    def _call(self, url: str, body: str, auth: bool = True) -> ET.Element:
        xml = (f'<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="{SOAP_ENV}" '
               f'xmlns:tds="{DEVICE_NS}" xmlns:trt="{MEDIA_NS}" xmlns:tt="{SCHEMA_NS}">'
               f"{self._security() if auth else ''}<s:Body>{body}</s:Body></s:Envelope>")
        req = Request(url, xml.encode(), {"Content-Type": "application/soap+xml; charset=utf-8"})
        try:
            with urlopen(req, timeout=self.timeout) as r:
                return ET.fromstring(r.read())
        except HTTPError as e:
            detail = ""
            try:
                detail = _text(ET.fromstring(e.read()), "Text")
            except ET.ParseError:
                pass
            if e.code == 404:   # e.g. a Hikvision camera with ONVIF switched off (the default)
                raise OnvifError(f"{self.ip}:{self.port} has no ONVIF service. Turn ONVIF on in the camera's settings "
                                 "(Hikvision: Network > Advanced > Integration Protocol), or check the ONVIF port") from e
            # a bad login is HTTP 401/403, or a 400 SOAP fault saying "not authorized"
            if e.code in (401, 403) or "auth" in detail.lower():
                raise OnvifError(f"{self.ip} refused the ONVIF login. Check the username/password; on Hikvision, "
                                 "enable ONVIF (Network > Advanced > Integration Protocol) and add an ONVIF user") from e
            raise OnvifError(f"{self.ip}: ONVIF request failed (HTTP {e.code}{': ' + detail if detail else ''})") from e
        except (URLError, OSError) as e:
            raise OnvifError(f"{self.ip}:{self.port} didn't answer ONVIF ({getattr(e, 'reason', e)}). "
                             "Is ONVIF enabled, and is this its ONVIF port?") from e
        except ET.ParseError as e:
            raise OnvifError(f"{self.ip}: the reply wasn't ONVIF (wrong port?)") from e

    def _camera_clock_offset(self) -> dt.timedelta:
        try:
            r = self._call(self.device_url, "<tds:GetSystemDateAndTime/>", auth=False)
            utc = _find(r, "UTCDateTime")
            d, t = _find(utc, "Date"), _find(utc, "Time")
            cam = dt.datetime(int(_text(d, "Year")), int(_text(d, "Month")), int(_text(d, "Day")),
                              int(_text(t, "Hour")), int(_text(t, "Minute")), int(_text(t, "Second")),
                              tzinfo=dt.timezone.utc)
            return cam - dt.datetime.now(dt.timezone.utc)
        except (OnvifError, TypeError, ValueError):
            return dt.timedelta(0)   # no usable clock: assume it's in sync

    # ---------- media ----------
    def media_url(self) -> str:
        r = self._call(self.device_url, "<tds:GetCapabilities><tds:Category>Media</tds:Category></tds:GetCapabilities>")
        xaddr = _text(_find(r, "Media"), "XAddr")
        if not xaddr:
            return f"http://{self.ip}:{self.port}/onvif/Media"
        # cameras behind NAT/Docker sometimes report an address we can't reach: keep their path only
        u = urlsplit(xaddr)
        return urlunsplit(("http", f"{self.ip}:{u.port or self.port}", u.path, u.query, ""))

    def profiles(self) -> list[dict]:
        """Stream profiles, e.g. [{token, name, encoding, width, height, fps}], main stream first."""
        r = self._call(self.media_url(), "<trt:GetProfiles/>")
        out = []
        for p in _findall(r, "Profiles"):
            venc = _find(p, "VideoEncoderConfiguration")
            res = _find(venc, "Resolution") if venc is not None else None
            out.append({
                "token": p.get("token", ""),
                "name": _text(p, "Name"),
                "encoding": _text(venc, "Encoding"),
                "width": int(_text(res, "Width", "0") or 0),
                "height": int(_text(res, "Height", "0") or 0),
                "fps": float(_text(_find(venc, "RateControl") if venc is not None else None, "FrameRateLimit", "0") or 0),
            })
        if not out:
            raise OnvifError(f"{self.ip} has no ONVIF stream profiles")
        return out

    def stream_uri(self, profile: str = "") -> str:
        """RTSP address of a profile (token or name; empty = the highest resolution), with the login
        added to it so OpenCV can open it."""
        profs = self.profiles()
        if profile:
            match = [p for p in profs if profile in (p["token"], p["name"])]
            if not match:
                names = ", ".join(p["token"] for p in profs)
                raise OnvifError(f"{self.ip} has no profile {profile!r} (it has: {names})")
            chosen = match[0]
        else:
            chosen = max(profs, key=lambda p: p["width"] * p["height"])
        body = ("<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream>"
                "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>"
                f"<trt:ProfileToken>{escape(chosen['token'])}</trt:ProfileToken></trt:GetStreamUri>")
        uri = _text(self._call(self.media_url(), body), "Uri")
        if not uri:
            raise OnvifError(f"{self.ip} didn't return a stream address for {chosen['token']}")
        return with_login(uri, self.user, self.password)


def with_login(uri: str, user: str, password: str) -> str:
    """Put the login into an RTSP URI (cameras return it without one)."""
    u = urlsplit(uri)
    if not user or "@" in u.netloc:
        return uri
    return urlunsplit((u.scheme, f"{quote(user, safe='')}:{quote(password, safe='')}@{u.netloc}",
                       u.path, u.query, u.fragment))


# ---------- discovery ----------
PROBE = ('<?xml version="1.0" encoding="UTF-8"?>'
         f'<e:Envelope xmlns:e="{SOAP_ENV}" xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
         'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
         "<e:Header><w:MessageID>uuid:{id}</w:MessageID>"
         '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
         '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
         "</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>")


def parse_probe_match(data: bytes) -> dict | None:
    """One WS-Discovery reply -> {ip, port, name, hardware, xaddr}, or None if it isn't a camera."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    xaddrs = _text(root, "XAddrs").split()
    scopes = _text(root, "Scopes").split()
    # other WS-Discovery devices (Windows PCs, NAS boxes, printers) answer probes too
    is_camera = "NetworkVideoTransmitter" in _text(root, "Types") or any(s.startswith("onvif://") for s in scopes)
    if not xaddrs or not is_camera:
        return None
    u = urlsplit(xaddrs[0])
    def scope(kind):
        vals = [s.split(f"/{kind}/", 1)[1] for s in scopes if f"onvif://www.onvif.org/{kind}/" in s]
        return vals[0].replace("%20", " ").replace("_", " ") if vals else ""
    return {"ip": u.hostname, "port": u.port or 80, "name": scope("name"), "hardware": scope("hardware"),
            "xaddr": xaddrs[0]}


def discover(timeout: float = 2.5) -> list[dict]:
    """ONVIF cameras on the local network (WS-Discovery multicast probe). Doesn't reach across
    routers or out of a Docker bridge network."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.3)
    found: dict[str, dict] = {}
    try:
        sock.bind(("", 0))
        for _ in range(2):   # UDP can drop a probe
            sock.sendto(PROBE.format(id=uuid.uuid4()).encode(), DISCOVERY_ADDR)
        deadline = dt.datetime.now() + dt.timedelta(seconds=timeout)
        while dt.datetime.now() < deadline:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            cam = parse_probe_match(data)
            if cam and cam["ip"]:
                found.setdefault(cam["ip"], cam)
    finally:
        sock.close()
    return sorted(found.values(), key=lambda c: tuple(int(x) for x in c["ip"].split(".") if x.isdigit()))
