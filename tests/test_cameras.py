"""Intrinsics -> CARLA FOV mapping tests (gate G1)."""

import math

import pytest

from alpasim_carla._proto.alpasim_grpc.v0 import sensorsim_pb2
from alpasim_carla.cameras import (
    UnsupportedCameraError,
    pinhole_hfov_deg,
    resolve_camera,
)

# The recorded hyperion 120-degree ftheta polynomial (cross_left camera,
# production rollout.asl): pixeldist -> angle, lowest order first.
HYPERION_120FOV_POLY = [
    0.0,
    0.0010593472979962826,
    3.79588946941567e-08,
    -1.0332284333669506e-10,
    1.5462011824975835e-13,
    -5.4741773999910005e-17,
]


def pinhole_spec(fx=960.0, fy=960.0, cx=960.0, cy=540.0, w=1920, h=1080, logical_id="cam"):
    spec = sensorsim_pb2.CameraSpec(
        logical_id=logical_id, resolution_w=w, resolution_h=h,
        shutter_type=sensorsim_pb2.ShutterType.GLOBAL,
    )
    spec.opencv_pinhole_param.focal_length_x = fx
    spec.opencv_pinhole_param.focal_length_y = fy
    spec.opencv_pinhole_param.principal_point_x = cx
    spec.opencv_pinhole_param.principal_point_y = cy
    return spec


def ftheta_spec(poly=HYPERION_120FOV_POLY, w=1920, h=1080, shutter=sensorsim_pb2.ShutterType.ROLLING_TOP_TO_BOTTOM):
    spec = sensorsim_pb2.CameraSpec(
        logical_id="ftheta_cam", resolution_w=w, resolution_h=h, shutter_type=shutter
    )
    spec.ftheta_param.principal_point_x = w / 2
    spec.ftheta_param.principal_point_y = h / 2
    spec.ftheta_param.reference_poly = (
        sensorsim_pb2.FthetaCameraParam.PolynomialType.ANGLE_TO_PIXELDIST
    )
    spec.ftheta_param.pixeldist_to_angle_poly.extend(poly)
    return spec


def test_ideal_pinhole_hfov():
    # fx=960px at width 1920 -> hfov = 2*atan(960/960) = 90 deg exactly.
    resolved = resolve_camera(pinhole_spec(), 1920, 1080, allow_approximation=False)
    assert resolved.hfov_deg == pytest.approx(90.0, abs=1e-9)
    assert not resolved.is_approximate
    assert pinhole_hfov_deg(960.0, 1920) == pytest.approx(90.0, abs=1e-9)


def test_pinhole_narrower_request_is_center_crop():
    # Requesting 1900px wide on a 1920-native sensor: hfov shrinks to the
    # angle subtended by 1900px (center-crop semantics, see CONTRACT.md).
    resolved = resolve_camera(pinhole_spec(), 1900, 1080, allow_approximation=False)
    assert resolved.hfov_deg == pytest.approx(
        math.degrees(2 * math.atan2(950, 960)), abs=1e-9
    )


def test_pinhole_telephoto():
    # fx = 2400px, width 1920 -> 2*atan(960/2400) = 43.60 deg (hand-computed).
    resolved = resolve_camera(pinhole_spec(fx=2400.0), 1920, 1080, allow_approximation=False)
    assert resolved.hfov_deg == pytest.approx(43.60281897270363, abs=1e-9)


def test_pinhole_distortion_rejected_without_flag():
    spec = pinhole_spec()
    spec.opencv_pinhole_param.radial_coeffs.extend([0.1, 0.0, 0.0])
    with pytest.raises(UnsupportedCameraError) as exc:
        resolve_camera(spec, 1920, 1080, allow_approximation=False)
    assert "radial_coeffs" in str(exc.value)
    assert "--allow-pinhole-approximation" in str(exc.value)


def test_pinhole_distortion_allowed_with_flag():
    spec = pinhole_spec()
    spec.opencv_pinhole_param.radial_coeffs.extend([0.1])
    resolved = resolve_camera(spec, 1920, 1080, allow_approximation=True)
    assert resolved.is_approximate
    assert any("distortion" in note for note in resolved.approximation_notes)


def test_offcenter_principal_point_rejected():
    spec = pinhole_spec(cx=830.0)  # 130px off-center > 2% of 1920
    with pytest.raises(UnsupportedCameraError) as exc:
        resolve_camera(spec, 1920, 1080, allow_approximation=False)
    assert "principal_point_x" in str(exc.value)


def test_ftheta_rejected_without_flag():
    with pytest.raises(UnsupportedCameraError) as exc:
        resolve_camera(ftheta_spec(), 1920, 1080, allow_approximation=False)
    assert "ftheta_param" in str(exc.value)
    assert "--allow-pinhole-approximation" in str(exc.value)


def test_ftheta_recorded_poly_is_120deg_with_flag():
    # The "camera_cross_left_120fov" polynomial must evaluate to ~120 deg
    # total horizontal FOV at the native 1920px width.
    resolved = resolve_camera(ftheta_spec(), 1920, 1080, allow_approximation=True)
    assert resolved.hfov_deg == pytest.approx(120.0, abs=1.5)
    assert resolved.is_approximate


def test_rolling_shutter_needs_flag_even_for_pinhole():
    spec = pinhole_spec()
    spec.shutter_type = sensorsim_pb2.ShutterType.ROLLING_TOP_TO_BOTTOM
    with pytest.raises(UnsupportedCameraError) as exc:
        resolve_camera(spec, 1920, 1080, allow_approximation=False)
    assert "shutter_type" in str(exc.value)
    resolved = resolve_camera(spec, 1920, 1080, allow_approximation=True)
    assert any("shutter" in note for note in resolved.approximation_notes)


def test_unset_camera_param_rejected():
    spec = sensorsim_pb2.CameraSpec(resolution_w=1920, resolution_h=1080)
    with pytest.raises(UnsupportedCameraError) as exc:
        resolve_camera(spec, 1920, 1080, allow_approximation=True)
    assert "camera_param is unset" in str(exc.value)


def test_windshield_model_rejected_without_flag():
    spec = pinhole_spec()
    spec.bivariate_windshield_model_param.horizontal_poly.extend([0.0, 1.0])
    with pytest.raises(UnsupportedCameraError) as exc:
        resolve_camera(spec, 1920, 1080, allow_approximation=False)
    assert "windshield" in str(exc.value)
