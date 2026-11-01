import math

import numpy as np
import pytest

from eyetracker.geometry import CameraModel, _basis, eye_angles, servo_us, triangulate

CAM_LEFT = {"position": [-6.0, 0.0, 3.0], "heading": 40.0, "pitch": -15.0, "roll": 0.0, "hfov": 90.0}
CAM_RIGHT = {"position": [6.0, 0.0, 3.0], "heading": -40.0, "pitch": -15.0, "roll": 0.0, "hfov": 90.0}
W, H = 1280, 720


def person_box(cam: CameraModel, x, y, face_h, top_h):
    """Synthetic detection: box from head top to feet, plus the exact eye pixel."""
    face, feet, top = cam.project((x, y, face_h)), cam.project((x, y, 0)), cam.project((x, y, top_h))
    half = (feet[1] - top[1]) * 0.25
    return (face[0] - half, top[1], face[0] + half, feet[1]), face


def test_basis_heading_zero_looks_at_street():
    fwd, right, up = _basis(0, 0)
    assert np.allclose(fwd, [0, 1, 0]) and np.allclose(right, [1, 0, 0]) and np.allclose(up, [0, 0, 1])


def test_basis_heading_90_looks_right():
    fwd, _, _ = _basis(90, 0)
    assert np.allclose(fwd, [1, 0, 0], atol=1e-9)


def test_project_center_pixel_is_optical_axis():
    cam = CameraModel(CAM_LEFT, W, H)
    point = cam.pos + cam.fwd * 10
    u, v = cam.project(point)
    assert u == pytest.approx(W / 2) and v == pytest.approx(H / 2)


def test_project_behind_camera_is_none():
    cam = CameraModel(CAM_LEFT, W, H)
    assert cam.project(cam.pos - cam.fwd * 5) is None


@pytest.mark.parametrize("x,y,face_h", [(2, 7, 1.60), (-3, 9, 1.05), (0, 5, 1.62), (1, 12, 1.75)])
def test_locate_recovers_position_and_eye_height(x, y, face_h):
    cam = CameraModel(CAM_LEFT, W, H)
    box, face = person_box(cam, x, y, face_h, face_h + 0.12)
    loc = cam.locate(box, face, default_face_h=1.55)
    assert loc.x == pytest.approx(x, abs=0.1)
    assert loc.y == pytest.approx(y, abs=0.1)
    assert loc.face_h == pytest.approx(face_h, abs=0.03)


def test_locate_with_feet_cut_off_uses_default_height():
    cam = CameraModel(CAM_LEFT, W, H)
    box, face = person_box(cam, 0, 5, 1.55, 1.67)
    clipped = (box[0], box[1], box[2], H)       # bottom of the frame -> feet not visible
    loc = cam.locate(clipped, face, default_face_h=1.55)
    assert loc.face_h is None
    assert loc.x == pytest.approx(0, abs=0.2) and loc.y == pytest.approx(5, abs=0.2)


def test_triangulate_two_cameras_recovers_face():
    left, right = CameraModel(CAM_LEFT, W, H), CameraModel(CAM_RIGHT, W, H)
    target = np.array([1.0, 8.0, 1.4])
    rays = [(c.pos, c.ray(*c.project(target))) for c in (left, right)]
    p = triangulate(*rays[0], *rays[1])
    assert np.allclose(p, target, atol=1e-6)


def test_triangulate_rejects_parallel_rays():
    d = np.array([0.0, 1.0, 0.0])
    assert triangulate(np.zeros(3), d, np.array([0.1, 0, 0]), d) is None


def test_triangulate_rejects_rays_that_miss():
    o1, d1 = np.array([0.0, 0, 1.5]), np.array([0.0, 1, 0])
    o2, d2 = np.array([5.0, 5, 3.0]), np.array([-1.0, 0, 0])   # passes 1.5 m above the first ray
    assert triangulate(o1, d1, o2, d2) is None


def test_eye_angles():
    eye = {"position": [0, 0, 1.2], "heading": 0, "pitch": 0}
    assert eye_angles(eye, (0, 10), 1.2) == pytest.approx((0, 0))
    pan, _ = eye_angles(eye, (5, 5), 1.2)
    assert pan == pytest.approx(45)                          # +pan = toward +X (right)
    _, tilt = eye_angles(eye, (0, 10), 1.2 + 10 * math.tan(math.radians(10)))
    assert tilt == pytest.approx(10)
    turned = dict(eye, heading=30)
    assert eye_angles(turned, (5, 5), 1.2)[0] == pytest.approx(15)


def test_servo_us_maps_and_clamps():
    axis = {"center": 1500, "us_per_deg": 30, "min": -20, "max": 20}
    assert servo_us(axis, 0) == 1500
    assert servo_us(axis, 10) == 1800
    assert servo_us(axis, 50) == 2100                        # clamped to +20 deg
    assert servo_us(dict(axis, us_per_deg=-30), 10) == 1200  # reversed servo
