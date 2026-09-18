"""AlpaSim <-> Unreal frame conversions.

The implementation now lives in the ``simforge-frames`` distribution
(``packages/simforge-frames/``), because ``simforge-closed-loop`` needs the
same conversions and cannot import this package: ``alpasim_carla.scenes``
pulls generated stubs for ``alpasim_grpc`` 0.54.0, the closed-loop repo
carries 0.55.0, and protobuf's descriptor pool is global.

This module re-exports it verbatim so nothing in the bridge changes. Import
either name; they are the same objects.
"""

from simforge_frames import *  # noqa: F401,F403
from simforge_frames import (  # noqa: F401  explicit for the non-star importers
    Quat,
    Rotator,
    Vec3,
    actor_location_for_bbox_center,
    alpasim_pose_from_carla,
    apply_anchor,
    carla_transform_tuple,
    compose,
    enu_to_ue_position,
    grpc_pose_to_tuple,
    inverse,
    matrix_to_quat,
    quat_conjugate,
    quat_from_rotator,
    quat_multiply,
    quat_normalize,
    quat_rotate,
    quat_to_matrix,
    rotator_from_quat,
    rotator_to_ue_matrix,
    ue_to_enu_position,
)
