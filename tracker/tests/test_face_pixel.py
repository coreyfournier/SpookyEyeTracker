import numpy as np
import pytest

from eyetracker.camera import EYE_FRACTION, face_pixel

BOX = (100.0, 100.0, 200.0, 420.0)   # 320 px tall person


def kps(**points):
    """17 COCO keypoints, all invisible except the given ones: name=(x, y)."""
    names = ["nose", "l_eye", "r_eye", "l_ear", "r_ear", "l_sh", "r_sh"]
    k = np.zeros((17, 3))
    for name, (x, y) in points.items():
        k[names.index(name)] = (x, y, 0.9)
    return k


def test_uses_eyes_and_nose_when_visible():
    assert face_pixel(BOX, kps(l_eye=(140, 120), r_eye=(160, 120), nose=(150, 126)), True) == \
        pytest.approx((150, 122))


def test_falls_back_to_ears_when_facing_away():
    assert face_pixel(BOX, kps(l_ear=(130, 118), r_ear=(170, 122)), True) == pytest.approx((150, 120))


def test_falls_back_to_shoulders():
    x, y = face_pixel(BOX, kps(l_sh=(120, 160), r_sh=(180, 160)), True)
    assert x == pytest.approx(150)
    assert 100 < y < 160                                  # between head top and shoulders


def test_box_only_full_body_uses_one_sixteenth():
    assert face_pixel(BOX, None, True) == pytest.approx((150, 100 + 320 * EYE_FRACTION))


def test_box_only_cut_off_body_uses_width_not_height():
    x, y = face_pixel(BOX, None, False)
    assert x == pytest.approx(150)
    assert y == pytest.approx(100 + 0.12 * 100)


def test_low_confidence_keypoints_are_ignored():
    k = kps(nose=(150, 300))
    k[0, 2] = 0.1
    assert face_pixel(BOX, k, True) == face_pixel(BOX, None, True)
