"""Golden tests for the AlpaSim<->CARLA frame math (gate G1).

Hand-computed fixtures first, then property tests (round-trips), then
fixtures lifted from real recorded data (the hyperion rig_to_camera poses
decoded from a production rollout.asl).
"""

import math

import numpy as np
import pytest

from alpasim_carla import frames

DEG = math.degrees


def quat_about_z(angle_rad):
    return (math.cos(angle_rad / 2), 0.0, 0.0, math.sin(angle_rad / 2))


def quat_about_y(angle_rad):
    return (math.cos(angle_rad / 2), 0.0, math.sin(angle_rad / 2), 0.0)


def quat_about_x(angle_rad):
    return (math.cos(angle_rad / 2), math.sin(angle_rad / 2), 0.0, 0.0)


# ---------------------------------------------------------------------------
# SE(3) primitives
# ---------------------------------------------------------------------------


def test_compose_matches_alpasim_pose_semantics():
    # Empirically verified against alpasim_utils.geometry.Pose (utils_rs):
    # (vec=(1,2,3), Rz90) @ (vec=(1,0,0), I) -> vec=(1,3,3), quat=Rz90.
    pose_a = ((1.0, 2.0, 3.0), quat_about_z(math.pi / 2))
    pose_b = ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))
    (vec, quat) = frames.compose(pose_a, pose_b)
    assert vec == pytest.approx((1.0, 3.0, 3.0), abs=1e-12)
    assert quat == pytest.approx(quat_about_z(math.pi / 2), abs=1e-12)


def test_inverse_roundtrip():
    pose = ((4.4, -2.1, 0.8), frames.quat_normalize((0.9, 0.1, -0.2, 0.35)))
    vec, quat = frames.compose(pose, frames.inverse(pose))
    assert vec == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    assert abs(quat[0]) == pytest.approx(1.0, abs=1e-12)


def test_quat_matrix_roundtrip():
    rng = np.random.default_rng(7)
    for _ in range(50):
        raw = tuple(rng.normal(size=4))
        if abs(np.linalg.norm(raw)) < 1e-6:
            continue
        q = frames.quat_normalize(raw)
        q2 = frames.matrix_to_quat(frames.quat_to_matrix(q))
        # q and -q encode the same rotation; matrix_to_quat returns w >= 0.
        if q[0] < 0:
            q = tuple(-c for c in q)
        assert q2 == pytest.approx(q, abs=1e-9)


# ---------------------------------------------------------------------------
# Hand-computed ENU->UE fixtures
# ---------------------------------------------------------------------------


def test_position_handedness_flip():
    assert frames.enu_to_ue_position((1.0, 2.0, 3.0)) == (1.0, -2.0, 3.0)
    assert frames.ue_to_enu_position((1.0, -2.0, 3.0)) == (1.0, 2.0, 3.0)


def test_identity_flu_pose_is_zero_rotator():
    # Fixture 1 (hand-computed): a body at ENU origin facing east (+x) with
    # FLU axes maps to CARLA rotator (0, 0, 0).
    pitch, yaw, roll = frames.rotator_from_quat((1.0, 0.0, 0.0, 0.0), axes="flu")
    assert (pitch, yaw, roll) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_yaw_90_faces_north_maps_to_ue_yaw_minus_90():
    # Fixture 2 (hand-computed): ENU yaw +90 deg (facing north, +y).
    # UE +y is SOUTH (y flipped), so facing north is UE yaw -90.
    pitch, yaw, roll = frames.rotator_from_quat(quat_about_z(math.pi / 2), axes="flu")
    assert pitch == pytest.approx(0.0, abs=1e-9)
    assert yaw == pytest.approx(-90.0, abs=1e-9)
    assert roll == pytest.approx(0.0, abs=1e-9)


def test_pitch_30_up_maps_to_ue_pitch_plus_30():
    # Fixture 3 (hand-computed): nose up 30 deg while facing east. In RH FLU,
    # nose-up is a NEGATIVE rotation about +y(left): fwd = (cos30, 0, sin30).
    # UE pitch is positive-up: expect +30.
    q = quat_about_y(-math.pi / 6)
    pitch, yaw, roll = frames.rotator_from_quat(q, axes="flu")
    assert pitch == pytest.approx(30.0, abs=1e-9)
    assert yaw == pytest.approx(0.0, abs=1e-9)
    assert roll == pytest.approx(0.0, abs=1e-9)


def test_roll_45_right_wing_down():
    # Fixture 4 (hand-computed): roll +45 deg about ENU +x while facing east.
    # The body's left(+y) axis tips up; its right(-y) axis tips down. In UE,
    # positive roll is clockwise looking along +x (right side down): +45.
    q = quat_about_x(math.pi / 4)
    pitch, yaw, roll = frames.rotator_from_quat(q, axes="flu")
    assert pitch == pytest.approx(0.0, abs=1e-9)
    assert yaw == pytest.approx(0.0, abs=1e-9)
    assert roll == pytest.approx(45.0, abs=1e-9)


def test_translation_composes_with_anchor():
    anchored = frames.apply_anchor(
        (100.0, 50.0, 0.0), 90.0, ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))
    )
    (vec, quat) = anchored
    assert vec == pytest.approx((100.0, 51.0, 0.0), abs=1e-9)
    pitch, yaw, roll = frames.rotator_from_quat(quat, axes="flu")
    assert yaw == pytest.approx(-90.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Camera (optical-frame) fixtures - from the recorded hyperion rig
# ---------------------------------------------------------------------------

# Recorded rig_to_camera rotations from a production rollout.asl
# (alpasim_alpamayo15_nurec_main_20s eval, scene clipgt-2036568b-...).
FRONT_WIDE_QUAT = (-0.5, 0.496, -0.494, 0.509)
CROSS_LEFT_QUAT = (0.697, -0.688, 0.142, -0.145)
CROSS_RIGHT_QUAT = (-0.133, 0.145, -0.689, 0.698)


def test_front_wide_camera_looks_forward():
    # A forward-looking camera mounted on an identity rig pose must map to a
    # (near-)zero CARLA rotator: optical z-forward aligns with UE x-forward.
    q = frames.quat_normalize(FRONT_WIDE_QUAT)
    pitch, yaw, roll = frames.rotator_from_quat(q, axes="optical")
    # Real rig is not mounted perfectly straight; allow ~2 deg.
    assert abs(pitch) < 2.0
    assert abs(yaw) < 2.0
    assert abs(roll) < 2.0


def test_cross_left_camera_looks_left():
    q = frames.quat_normalize(CROSS_LEFT_QUAT)
    _, yaw, _ = frames.rotator_from_quat(q, axes="optical")
    # rig +y is LEFT; left of forward in UE is negative yaw.
    assert -120.0 < yaw < -10.0


def test_cross_right_camera_looks_right():
    q = frames.quat_normalize(CROSS_RIGHT_QUAT)
    _, yaw, _ = frames.rotator_from_quat(q, axes="optical")
    assert 10.0 < yaw < 120.0


def test_left_right_cameras_are_mirrored():
    _, yaw_l, _ = frames.rotator_from_quat(
        frames.quat_normalize(CROSS_LEFT_QUAT), axes="optical"
    )
    _, yaw_r, _ = frames.rotator_from_quat(
        frames.quat_normalize(CROSS_RIGHT_QUAT), axes="optical"
    )
    assert yaw_l == pytest.approx(-yaw_r, abs=2.0)


def test_exact_ideal_optical_quat_is_identity_rotator():
    # The idealized FLU->optical rotation: x_cam=-y_rig(right), y_cam=-z_rig
    # (down), z_cam=+x_rig (forward) <=> quat (0.5, -0.5, 0.5, -0.5).
    pitch, yaw, roll = frames.rotator_from_quat((0.5, -0.5, 0.5, -0.5), axes="optical")
    assert (pitch, yaw, roll) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


# ---------------------------------------------------------------------------
# Round-trips (gate requirement: alpasim -> carla -> alpasim within 1e-5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axes", ["flu", "optical"])
def test_pose_roundtrip_through_carla(axes):
    rng = np.random.default_rng(42)
    for _ in range(200):
        raw = tuple(rng.normal(size=4))
        q = frames.quat_normalize(raw)
        # Avoid the rotator gimbal singularity at |pitch| = 90 deg.
        location, rotator = frames.carla_transform_tuple((0, 0, 0), q, axes=axes)
        if abs(abs(rotator[0]) - 90.0) < 0.5:
            continue
        vec = tuple(rng.uniform(-100, 100, size=3))
        location, rotator = frames.carla_transform_tuple(vec, q, axes=axes)
        vec_back, q_back = frames.alpasim_pose_from_carla(location, rotator, axes=axes)
        assert vec_back == pytest.approx(vec, abs=1e-5)
        if q[0] < 0:
            q = tuple(-c for c in q)
        assert q_back == pytest.approx(q, abs=1e-5)


def test_rotator_to_matrix_matches_carla_reference():
    # Spot-check against carla.Transform.get_matrix()'s documented expansion.
    m = frames.rotator_to_ue_matrix((10.0, 20.0, 30.0))
    cy, sy = math.cos(math.radians(20)), math.sin(math.radians(20))
    cp, sp = math.cos(math.radians(10)), math.sin(math.radians(10))
    cr, sr = math.cos(math.radians(30)), math.sin(math.radians(30))
    expected = np.array(
        [
            [cp * cy, cy * sp * sr - sy * cr, -cy * sp * cr - sy * sr],
            [cp * sy, sy * sp * sr + cy * cr, -sy * sp * cr + cy * sr],
            [sp, -cp * sr, cp * cr],
        ]
    )
    assert np.allclose(m, expected, atol=1e-12)


# ---------------------------------------------------------------------------
# Bounding-box center handling
# ---------------------------------------------------------------------------


def test_actor_location_for_bbox_center_identity_rotation():
    loc = frames.actor_location_for_bbox_center((10.0, 5.0, 1.0), (0, 0, 0), (0.0, 0.0, 0.7))
    assert loc == pytest.approx((10.0, 5.0, 0.3), abs=1e-12)


def test_actor_location_for_bbox_center_with_yaw():
    # bbox center offset 1m forward in actor frame, actor yawed 90 deg:
    # forward is UE +y, so the actor origin must sit 1m at -y from the center.
    loc = frames.actor_location_for_bbox_center((0.0, 0.0, 0.0), (0, 90, 0), (1.0, 0.0, 0.0))
    assert loc == pytest.approx((0.0, -1.0, 0.0), abs=1e-9)
