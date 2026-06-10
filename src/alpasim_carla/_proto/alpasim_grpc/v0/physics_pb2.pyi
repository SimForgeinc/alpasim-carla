from alpasim_carla._proto.alpasim_grpc.v0 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PhysicsGroundIntersectionRequest(_message.Message):
    __slots__ = ("scene_id", "now_us", "future_us", "ego_data", "other_objects")
    class PosePair(_message.Message):
        __slots__ = ("now_pose", "future_pose")
        NOW_POSE_FIELD_NUMBER: _ClassVar[int]
        FUTURE_POSE_FIELD_NUMBER: _ClassVar[int]
        now_pose: _common_pb2.Pose
        future_pose: _common_pb2.Pose
        def __init__(self, now_pose: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ..., future_pose: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ...) -> None: ...
    class EgoData(_message.Message):
        __slots__ = ("aabb", "ego_trajectory_aabb")
        AABB_FIELD_NUMBER: _ClassVar[int]
        EGO_TRAJECTORY_AABB_FIELD_NUMBER: _ClassVar[int]
        aabb: _common_pb2.AABB
        ego_trajectory_aabb: _common_pb2.Trajectory
        def __init__(self, aabb: _Optional[_Union[_common_pb2.AABB, _Mapping]] = ..., ego_trajectory_aabb: _Optional[_Union[_common_pb2.Trajectory, _Mapping]] = ...) -> None: ...
    class OtherObject(_message.Message):
        __slots__ = ("aabb", "pose_pair")
        AABB_FIELD_NUMBER: _ClassVar[int]
        POSE_PAIR_FIELD_NUMBER: _ClassVar[int]
        aabb: _common_pb2.AABB
        pose_pair: PhysicsGroundIntersectionRequest.PosePair
        def __init__(self, aabb: _Optional[_Union[_common_pb2.AABB, _Mapping]] = ..., pose_pair: _Optional[_Union[PhysicsGroundIntersectionRequest.PosePair, _Mapping]] = ...) -> None: ...
    SCENE_ID_FIELD_NUMBER: _ClassVar[int]
    NOW_US_FIELD_NUMBER: _ClassVar[int]
    FUTURE_US_FIELD_NUMBER: _ClassVar[int]
    EGO_DATA_FIELD_NUMBER: _ClassVar[int]
    OTHER_OBJECTS_FIELD_NUMBER: _ClassVar[int]
    scene_id: str
    now_us: int
    future_us: int
    ego_data: PhysicsGroundIntersectionRequest.EgoData
    other_objects: _containers.RepeatedCompositeFieldContainer[PhysicsGroundIntersectionRequest.OtherObject]
    def __init__(self, scene_id: _Optional[str] = ..., now_us: _Optional[int] = ..., future_us: _Optional[int] = ..., ego_data: _Optional[_Union[PhysicsGroundIntersectionRequest.EgoData, _Mapping]] = ..., other_objects: _Optional[_Iterable[_Union[PhysicsGroundIntersectionRequest.OtherObject, _Mapping]]] = ...) -> None: ...

class PhysicsGroundIntersectionReturn(_message.Message):
    __slots__ = ("ego_trajectory_aabb", "ego_status", "other_poses")
    class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SUCCESSFUL_UPDATE: _ClassVar[PhysicsGroundIntersectionReturn.Status]
        UNKNOWN: _ClassVar[PhysicsGroundIntersectionReturn.Status]
        INSUFFICIENT_POINTS_FITPLANE: _ClassVar[PhysicsGroundIntersectionReturn.Status]
        HIGH_TRANSLATION: _ClassVar[PhysicsGroundIntersectionReturn.Status]
        HIGH_ROTATION: _ClassVar[PhysicsGroundIntersectionReturn.Status]
    SUCCESSFUL_UPDATE: PhysicsGroundIntersectionReturn.Status
    UNKNOWN: PhysicsGroundIntersectionReturn.Status
    INSUFFICIENT_POINTS_FITPLANE: PhysicsGroundIntersectionReturn.Status
    HIGH_TRANSLATION: PhysicsGroundIntersectionReturn.Status
    HIGH_ROTATION: PhysicsGroundIntersectionReturn.Status
    class ReturnPose(_message.Message):
        __slots__ = ("pose", "status")
        POSE_FIELD_NUMBER: _ClassVar[int]
        STATUS_FIELD_NUMBER: _ClassVar[int]
        pose: _common_pb2.Pose
        status: PhysicsGroundIntersectionReturn.Status
        def __init__(self, pose: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ..., status: _Optional[_Union[PhysicsGroundIntersectionReturn.Status, str]] = ...) -> None: ...
    EGO_TRAJECTORY_AABB_FIELD_NUMBER: _ClassVar[int]
    EGO_STATUS_FIELD_NUMBER: _ClassVar[int]
    OTHER_POSES_FIELD_NUMBER: _ClassVar[int]
    ego_trajectory_aabb: _common_pb2.Trajectory
    ego_status: _containers.RepeatedScalarFieldContainer[PhysicsGroundIntersectionReturn.Status]
    other_poses: _containers.RepeatedCompositeFieldContainer[PhysicsGroundIntersectionReturn.ReturnPose]
    def __init__(self, ego_trajectory_aabb: _Optional[_Union[_common_pb2.Trajectory, _Mapping]] = ..., ego_status: _Optional[_Iterable[_Union[PhysicsGroundIntersectionReturn.Status, str]]] = ..., other_poses: _Optional[_Iterable[_Union[PhysicsGroundIntersectionReturn.ReturnPose, _Mapping]]] = ...) -> None: ...
