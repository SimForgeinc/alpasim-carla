"""Pure coordinate-frame conversions between AlpaSim and CARLA/Unreal.

Every pose or vector that crosses the AlpaSim<->CARLA boundary goes through
this module. It imports neither `carla` nor any gRPC code, so it is fully
testable without a simulator (gate G1).

AlpaSim conventions (verified against AlpaSim CONTRIBUTING.md "Coordinate
Systems" and the pinned protos at commit a1f05bb):
  * `local` frame: right-handed ENU, z-up.
  * `rig` / `aabb` body frames: x-forward, y-left, z-up (FLU); `aabb` origin
    is the bounding-box center.
  * camera frames: CV optical convention - x-right, y-down, z-forward
    (verified numerically from the recorded hyperion rig_to_camera
    quaternions, e.g. front_wide ~ (w,x,y,z)=(0.5,-0.5,0.5,-0.5)).
  * Poses are ACTIVE transforms `parent->child`; quaternions are (w, x, y, z);
    composition is standard SE(3): R = R1 R2, t = t1 + R1 t2 (verified
    empirically against alpasim_utils.geometry.Pose / utils_rs).

CARLA/Unreal conventions:
  * Left-handed, x-forward, y-RIGHT, z-up; angles in degrees.
  * `carla.Rotation(pitch, yaw, roll)` builds (per the CARLA client matrix)
        M = [[cp*cy, cy*sp*sr - sy*cr, -cy*sp*cr - sy*sr],
             [cp*sy, sy*sp*sr + cy*cr, -sy*sp*cr + cy*sr],
             [sp,    -cp*sr,            cp*cr           ]]
    whose columns are the actor's forward / right / up directions in UE
    world axes. Positive pitch is nose-up, positive yaw turns toward +y
    (clockwise seen from above).

The handedness bridge used throughout: ENU position (x, y, z) maps to UE
position (x, -y, z), and any *direction vector* maps the same way. Rotations
are transported by mapping the body axes (forward/right/up) as direction
vectors and re-assembling the UE rotation from them - transparent and easy
to golden-test, instead of opaque quaternion sign juggling.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple

import numpy as np

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]  # (w, x, y, z)
Rotator = Tuple[float, float, float]  # (pitch_deg, yaw_deg, roll_deg)


# ---------------------------------------------------------------------------
# Quaternion / SE(3) primitives (AlpaSim side, right-handed)
# ---------------------------------------------------------------------------


def quat_normalize(q: Quat) -> Quat:
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n == 0.0:
        raise ValueError("Cannot normalize zero quaternion")
    return (w / n, x / n, y / n, z / n)


def quat_multiply(a: Quat, b: Quat) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def quat_conjugate(q: Quat) -> Quat:
    w, x, y, z = q
    return (w, -x, -y, -z)


def quat_to_matrix(q: Quat) -> np.ndarray:
    w, x, y, z = quat_normalize(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def matrix_to_quat(m: np.ndarray) -> Quat:
    """Convert a proper rotation matrix to (w, x, y, z), w >= 0."""
    t = float(np.trace(m))
    if t > 0.0:
        s = math.sqrt(t + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = (w, x, y, z)
    if w < 0.0:
        q = (-w, -x, -y, -z)
    return quat_normalize(q)


def quat_rotate(q: Quat, v: Sequence[float]) -> Vec3:
    m = quat_to_matrix(q)
    out = m @ np.asarray(v, dtype=np.float64)
    return (float(out[0]), float(out[1]), float(out[2]))


def compose(pose_a: Tuple[Vec3, Quat], pose_b: Tuple[Vec3, Quat]) -> Tuple[Vec3, Quat]:
    """SE(3) composition `a @ b` matching alpasim_utils.geometry.Pose.

    t = t_a + R_a t_b ;  q = q_a * q_b   (verified empirically: composing
    (vec=(1,2,3), Rz90) with (vec=(1,0,0), I) yields vec=(1,3,3)).
    """
    ta, qa = pose_a
    tb, qb = pose_b
    rotated = quat_rotate(qa, tb)
    return (
        (ta[0] + rotated[0], ta[1] + rotated[1], ta[2] + rotated[2]),
        quat_normalize(quat_multiply(qa, qb)),
    )


def inverse(pose: Tuple[Vec3, Quat]) -> Tuple[Vec3, Quat]:
    t, q = pose
    qi = quat_conjugate(quat_normalize(q))
    ti = quat_rotate(qi, t)
    return ((-ti[0], -ti[1], -ti[2]), qi)


# ---------------------------------------------------------------------------
# Handedness bridge: ENU (right-handed) <-> UE (left-handed)
# ---------------------------------------------------------------------------


def enu_to_ue_position(v: Sequence[float]) -> Vec3:
    """ENU (x, y, z) -> UE (x, -y, z). Also valid for direction vectors."""
    return (float(v[0]), -float(v[1]), float(v[2]))


def ue_to_enu_position(v: Sequence[float]) -> Vec3:
    return (float(v[0]), -float(v[1]), float(v[2]))


# Body-axis directions, expressed in the body frame, for the two AlpaSim body
# conventions we must transport into UE:
#   FLU (rig / aabb frames):    forward=+x, right=-y, up=+z
#   optical (camera frames):    forward=+z, right=+x, up=-y
_BODY_AXES = {
    "flu": ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "optical": ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
}


def _ue_basis_from_quat(q: Quat, axes: str) -> np.ndarray:
    """Forward/right/up of the body, as UE world direction column vectors."""
    try:
        fwd_b, right_b, up_b = _BODY_AXES[axes]
    except KeyError:
        raise ValueError(f"Unknown body axes convention {axes!r}; expected one of {sorted(_BODY_AXES)}")
    m = quat_to_matrix(q)
    cols = []
    for axis in (fwd_b, right_b, up_b):
        enu_dir = m @ np.asarray(axis)
        cols.append(enu_to_ue_position(enu_dir))
    return np.array(cols, dtype=np.float64).T  # columns: fwd, right, up


def rotator_from_quat(q: Quat, axes: str = "flu") -> Rotator:
    """AlpaSim local->body quaternion -> CARLA Rotation (pitch, yaw, roll) deg.

    `axes` selects the body convention: "flu" for rig/aabb object poses,
    "optical" for camera sensor poses (CARLA camera actors look along +x with
    image-right = +y_UE and image-up = +z_UE, which corresponds to the
    optical frame's z / x / -y axes respectively).
    """
    basis = _ue_basis_from_quat(q, axes)
    fwd = basis[:, 0]
    up = basis[:, 2]
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, float(fwd[2])))))
    yaw = math.degrees(math.atan2(float(fwd[1]), float(fwd[0])))
    # Roll from the up vector re-expressed in the yaw/pitch-aligned frame:
    # with M = Rz(yaw)Ry'(pitch)Rx'(roll) per the CARLA matrix, the up column
    # is (-cy*sp*cr - sy*sr, -sy*sp*cr + cy*sr, cp*cr). Solve for roll using
    # the right column's z (-cp*sr) and up column's z (cp*cr).
    right = basis[:, 1]
    roll = math.degrees(math.atan2(-float(right[2]), float(up[2])))
    return (pitch, yaw, roll)


def rotator_to_ue_matrix(rotator: Rotator) -> np.ndarray:
    """CARLA Rotation -> UE rotation matrix (columns: forward, right, up).

    Mirrors carla.Transform.get_matrix()'s rotation block exactly.
    """
    pitch, yaw, roll = (math.radians(a) for a in rotator)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    return np.array(
        [
            [cp * cy, cy * sp * sr - sy * cr, -cy * sp * cr - sy * sr],
            [cp * sy, sy * sp * sr + cy * cr, -sy * sp * cr + cy * sr],
            [sp, -cp * sr, cp * cr],
        ],
        dtype=np.float64,
    )


def quat_from_rotator(rotator: Rotator, axes: str = "flu") -> Quat:
    """Inverse of rotator_from_quat: CARLA Rotation -> AlpaSim quaternion."""
    ue = rotator_to_ue_matrix(rotator)
    fwd_b, right_b, up_b = _BODY_AXES[axes]
    # ENU directions of the body axes:
    fwd_enu = np.asarray(ue_to_enu_position(ue[:, 0]))
    right_enu = np.asarray(ue_to_enu_position(ue[:, 1]))
    up_enu = np.asarray(ue_to_enu_position(ue[:, 2]))
    # Solve R * [fwd_b right_b up_b] = [fwd_enu right_enu up_enu]
    body = np.array([fwd_b, right_b, up_b], dtype=np.float64).T
    world = np.array([fwd_enu, right_enu, up_enu], dtype=np.float64).T
    rot = world @ np.linalg.inv(body)
    return matrix_to_quat(rot)


def carla_transform_tuple(
    vec: Sequence[float], quat: Quat, axes: str = "flu"
) -> Tuple[Vec3, Rotator]:
    """AlpaSim local->body pose -> (UE location, CARLA rotator)."""
    return (enu_to_ue_position(vec), rotator_from_quat(quat, axes=axes))


def alpasim_pose_from_carla(
    location: Sequence[float], rotator: Rotator, axes: str = "flu"
) -> Tuple[Vec3, Quat]:
    """Inverse mapping, for round-trip tests and reading back CARLA state."""
    return (ue_to_enu_position(location), quat_from_rotator(rotator, axes=axes))


# ---------------------------------------------------------------------------
# Bounding-box center -> actor origin
# ---------------------------------------------------------------------------


def actor_location_for_bbox_center(
    center_location_ue: Sequence[float],
    rotator: Rotator,
    bbox_offset_ue: Sequence[float],
) -> Vec3:
    """UE location to give a CARLA actor so its bounding-box center lands at
    `center_location_ue`.

    AlpaSim object poses are local->aabb (bbox CENTER), while a CARLA actor's
    transform places its own pivot; `actor.bounding_box.location` is the
    center offset in the actor frame: p_actor = p_center - R * offset.
    """
    rot = rotator_to_ue_matrix(rotator)
    offset_world = rot @ np.asarray(bbox_offset_ue, dtype=np.float64)
    return (
        float(center_location_ue[0] - offset_world[0]),
        float(center_location_ue[1] - offset_world[1]),
        float(center_location_ue[2] - offset_world[2]),
    )


# ---------------------------------------------------------------------------
# Scene anchoring
# ---------------------------------------------------------------------------


def apply_anchor(
    anchor_translation: Sequence[float],
    anchor_yaw_deg: float,
    pose: Tuple[Vec3, Quat],
) -> Tuple[Vec3, Quat]:
    """Map an AlpaSim-local pose into the CARLA map's ENU-equivalent frame.

    Scene manifests carry a `local_to_world` anchor (translation + yaw,
    applied in right-handed ENU space *before* the handedness conversion) so
    a recorded local frame can be positioned sensibly inside a stock town.
    """
    half = math.radians(anchor_yaw_deg) / 2.0
    anchor_quat: Quat = (math.cos(half), 0.0, 0.0, math.sin(half))
    anchor_pose = (
        (float(anchor_translation[0]), float(anchor_translation[1]), float(anchor_translation[2])),
        anchor_quat,
    )
    return compose(anchor_pose, pose)


def grpc_pose_to_tuple(grpc_pose) -> Tuple[Vec3, Quat]:
    """common.Pose proto -> ((x,y,z), (w,x,y,z)). Accepts any duck-typed proto."""
    v = grpc_pose.vec
    q = grpc_pose.quat
    return ((v.x, v.y, v.z), (q.w, q.x, q.y, q.z))
