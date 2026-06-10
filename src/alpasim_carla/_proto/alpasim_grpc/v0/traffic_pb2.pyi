from alpasim_carla._proto.alpasim_grpc.v0 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ObjectTrajectory(_message.Message):
    __slots__ = ("aabb", "trajectory", "object_id", "is_static")
    AABB_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_FIELD_NUMBER: _ClassVar[int]
    OBJECT_ID_FIELD_NUMBER: _ClassVar[int]
    IS_STATIC_FIELD_NUMBER: _ClassVar[int]
    aabb: _common_pb2.AABB
    trajectory: _common_pb2.Trajectory
    object_id: str
    is_static: bool
    def __init__(self, aabb: _Optional[_Union[_common_pb2.AABB, _Mapping]] = ..., trajectory: _Optional[_Union[_common_pb2.Trajectory, _Mapping]] = ..., object_id: _Optional[str] = ..., is_static: bool = ...) -> None: ...

class ObjectTrajectoryUpdate(_message.Message):
    __slots__ = ("object_id", "trajectory")
    OBJECT_ID_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_FIELD_NUMBER: _ClassVar[int]
    object_id: str
    trajectory: _common_pb2.Trajectory
    def __init__(self, object_id: _Optional[str] = ..., trajectory: _Optional[_Union[_common_pb2.Trajectory, _Mapping]] = ...) -> None: ...

class TrafficSessionRequest(_message.Message):
    __slots__ = ("session_uuid", "map_id", "random_seed", "logged_object_trajectories", "handover_time_us")
    SESSION_UUID_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    RANDOM_SEED_FIELD_NUMBER: _ClassVar[int]
    LOGGED_OBJECT_TRAJECTORIES_FIELD_NUMBER: _ClassVar[int]
    HANDOVER_TIME_US_FIELD_NUMBER: _ClassVar[int]
    session_uuid: str
    map_id: str
    random_seed: int
    logged_object_trajectories: _containers.RepeatedCompositeFieldContainer[ObjectTrajectory]
    handover_time_us: int
    def __init__(self, session_uuid: _Optional[str] = ..., map_id: _Optional[str] = ..., random_seed: _Optional[int] = ..., logged_object_trajectories: _Optional[_Iterable[_Union[ObjectTrajectory, _Mapping]]] = ..., handover_time_us: _Optional[int] = ...) -> None: ...

class TrafficSessionCloseRequest(_message.Message):
    __slots__ = ("session_uuid",)
    SESSION_UUID_FIELD_NUMBER: _ClassVar[int]
    session_uuid: str
    def __init__(self, session_uuid: _Optional[str] = ...) -> None: ...

class TrafficRequest(_message.Message):
    __slots__ = ("session_uuid", "time_query_us", "object_trajectory_updates")
    SESSION_UUID_FIELD_NUMBER: _ClassVar[int]
    TIME_QUERY_US_FIELD_NUMBER: _ClassVar[int]
    OBJECT_TRAJECTORY_UPDATES_FIELD_NUMBER: _ClassVar[int]
    session_uuid: str
    time_query_us: int
    object_trajectory_updates: _containers.RepeatedCompositeFieldContainer[ObjectTrajectoryUpdate]
    def __init__(self, session_uuid: _Optional[str] = ..., time_query_us: _Optional[int] = ..., object_trajectory_updates: _Optional[_Iterable[_Union[ObjectTrajectoryUpdate, _Mapping]]] = ...) -> None: ...

class TrafficReturn(_message.Message):
    __slots__ = ("object_trajectory_updates",)
    OBJECT_TRAJECTORY_UPDATES_FIELD_NUMBER: _ClassVar[int]
    object_trajectory_updates: _containers.RepeatedCompositeFieldContainer[ObjectTrajectoryUpdate]
    def __init__(self, object_trajectory_updates: _Optional[_Iterable[_Union[ObjectTrajectoryUpdate, _Mapping]]] = ...) -> None: ...

class TrafficModuleMetadata(_message.Message):
    __slots__ = ("version_id", "minimum_history_length_us", "supported_map_ids")
    VERSION_ID_FIELD_NUMBER: _ClassVar[int]
    MINIMUM_HISTORY_LENGTH_US_FIELD_NUMBER: _ClassVar[int]
    SUPPORTED_MAP_IDS_FIELD_NUMBER: _ClassVar[int]
    version_id: _common_pb2.VersionId
    minimum_history_length_us: int
    supported_map_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, version_id: _Optional[_Union[_common_pb2.VersionId, _Mapping]] = ..., minimum_history_length_us: _Optional[int] = ..., supported_map_ids: _Optional[_Iterable[str]] = ...) -> None: ...
