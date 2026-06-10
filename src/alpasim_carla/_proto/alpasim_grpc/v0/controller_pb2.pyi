from alpasim_carla._proto.alpasim_grpc.v0 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class VDCSessionRequest(_message.Message):
    __slots__ = ("session_uuid", "vehicle_and_controller_params")
    class VehicleAndControllerParams(_message.Message):
        __slots__ = ("rig_file", "amend_files")
        RIG_FILE_FIELD_NUMBER: _ClassVar[int]
        AMEND_FILES_FIELD_NUMBER: _ClassVar[int]
        rig_file: str
        amend_files: _containers.RepeatedScalarFieldContainer[str]
        def __init__(self, rig_file: _Optional[str] = ..., amend_files: _Optional[_Iterable[str]] = ...) -> None: ...
    SESSION_UUID_FIELD_NUMBER: _ClassVar[int]
    VEHICLE_AND_CONTROLLER_PARAMS_FIELD_NUMBER: _ClassVar[int]
    session_uuid: str
    vehicle_and_controller_params: VDCSessionRequest.VehicleAndControllerParams
    def __init__(self, session_uuid: _Optional[str] = ..., vehicle_and_controller_params: _Optional[_Union[VDCSessionRequest.VehicleAndControllerParams, _Mapping]] = ...) -> None: ...

class VDCSessionCloseRequest(_message.Message):
    __slots__ = ("session_uuid",)
    SESSION_UUID_FIELD_NUMBER: _ClassVar[int]
    session_uuid: str
    def __init__(self, session_uuid: _Optional[str] = ...) -> None: ...

class RunControllerAndVehicleModelRequest(_message.Message):
    __slots__ = ("session_uuid", "state", "planned_trajectory_in_rig", "future_time_us", "coerce_dynamic_state", "pose_reporting_interval_us")
    SESSION_UUID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PLANNED_TRAJECTORY_IN_RIG_FIELD_NUMBER: _ClassVar[int]
    FUTURE_TIME_US_FIELD_NUMBER: _ClassVar[int]
    COERCE_DYNAMIC_STATE_FIELD_NUMBER: _ClassVar[int]
    POSE_REPORTING_INTERVAL_US_FIELD_NUMBER: _ClassVar[int]
    session_uuid: str
    state: _common_pb2.StateAtTime
    planned_trajectory_in_rig: _common_pb2.Trajectory
    future_time_us: int
    coerce_dynamic_state: bool
    pose_reporting_interval_us: int
    def __init__(self, session_uuid: _Optional[str] = ..., state: _Optional[_Union[_common_pb2.StateAtTime, _Mapping]] = ..., planned_trajectory_in_rig: _Optional[_Union[_common_pb2.Trajectory, _Mapping]] = ..., future_time_us: _Optional[int] = ..., coerce_dynamic_state: bool = ..., pose_reporting_interval_us: _Optional[int] = ...) -> None: ...

class RunControllerAndVehicleModelResponse(_message.Message):
    __slots__ = ("pose_local_to_rig", "pose_local_to_rig_estimated", "dynamic_state", "dynamic_state_estimated", "states")
    class PropagatedState(_message.Message):
        __slots__ = ("timestamp_us", "pose_local_to_rig", "pose_local_to_rig_estimated", "dynamic_state", "dynamic_state_estimated")
        TIMESTAMP_US_FIELD_NUMBER: _ClassVar[int]
        POSE_LOCAL_TO_RIG_FIELD_NUMBER: _ClassVar[int]
        POSE_LOCAL_TO_RIG_ESTIMATED_FIELD_NUMBER: _ClassVar[int]
        DYNAMIC_STATE_FIELD_NUMBER: _ClassVar[int]
        DYNAMIC_STATE_ESTIMATED_FIELD_NUMBER: _ClassVar[int]
        timestamp_us: int
        pose_local_to_rig: _common_pb2.Pose
        pose_local_to_rig_estimated: _common_pb2.Pose
        dynamic_state: _common_pb2.DynamicState
        dynamic_state_estimated: _common_pb2.DynamicState
        def __init__(self, timestamp_us: _Optional[int] = ..., pose_local_to_rig: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ..., pose_local_to_rig_estimated: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ..., dynamic_state: _Optional[_Union[_common_pb2.DynamicState, _Mapping]] = ..., dynamic_state_estimated: _Optional[_Union[_common_pb2.DynamicState, _Mapping]] = ...) -> None: ...
    POSE_LOCAL_TO_RIG_FIELD_NUMBER: _ClassVar[int]
    POSE_LOCAL_TO_RIG_ESTIMATED_FIELD_NUMBER: _ClassVar[int]
    DYNAMIC_STATE_FIELD_NUMBER: _ClassVar[int]
    DYNAMIC_STATE_ESTIMATED_FIELD_NUMBER: _ClassVar[int]
    STATES_FIELD_NUMBER: _ClassVar[int]
    pose_local_to_rig: _common_pb2.PoseAtTime
    pose_local_to_rig_estimated: _common_pb2.PoseAtTime
    dynamic_state: _common_pb2.DynamicState
    dynamic_state_estimated: _common_pb2.DynamicState
    states: _containers.RepeatedCompositeFieldContainer[RunControllerAndVehicleModelResponse.PropagatedState]
    def __init__(self, pose_local_to_rig: _Optional[_Union[_common_pb2.PoseAtTime, _Mapping]] = ..., pose_local_to_rig_estimated: _Optional[_Union[_common_pb2.PoseAtTime, _Mapping]] = ..., dynamic_state: _Optional[_Union[_common_pb2.DynamicState, _Mapping]] = ..., dynamic_state_estimated: _Optional[_Union[_common_pb2.DynamicState, _Mapping]] = ..., states: _Optional[_Iterable[_Union[RunControllerAndVehicleModelResponse.PropagatedState, _Mapping]]] = ...) -> None: ...
