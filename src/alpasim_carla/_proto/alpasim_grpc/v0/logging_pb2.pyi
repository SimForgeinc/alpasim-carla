from alpasim_carla._proto.alpasim_grpc.v0 import common_pb2 as _common_pb2
from alpasim_carla._proto.alpasim_grpc.v0 import sensorsim_pb2 as _sensorsim_pb2
from alpasim_carla._proto.alpasim_grpc.v0 import egodriver_pb2 as _egodriver_pb2
from alpasim_carla._proto.alpasim_grpc.v0 import physics_pb2 as _physics_pb2
from alpasim_carla._proto.alpasim_grpc.v0 import traffic_pb2 as _traffic_pb2
from alpasim_carla._proto.alpasim_grpc.v0 import controller_pb2 as _controller_pb2
from alpasim_carla._proto.alpasim_grpc.v0 import video_model_pb2 as _video_model_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RolloutMetadata(_message.Message):
    __slots__ = ("session_metadata", "actor_definitions", "force_gt_duration", "version_ids", "rollout_index", "transform_ego_coords_rig_to_aabb", "ego_rig_recorded_ground_truth_trajectory")
    class VersionIds(_message.Message):
        __slots__ = ("runtime_version", "egodriver_version", "sensorsim_version", "physics_version", "traffic_version", "controller_version", "video_model_version")
        RUNTIME_VERSION_FIELD_NUMBER: _ClassVar[int]
        EGODRIVER_VERSION_FIELD_NUMBER: _ClassVar[int]
        SENSORSIM_VERSION_FIELD_NUMBER: _ClassVar[int]
        PHYSICS_VERSION_FIELD_NUMBER: _ClassVar[int]
        TRAFFIC_VERSION_FIELD_NUMBER: _ClassVar[int]
        CONTROLLER_VERSION_FIELD_NUMBER: _ClassVar[int]
        VIDEO_MODEL_VERSION_FIELD_NUMBER: _ClassVar[int]
        runtime_version: _common_pb2.VersionId
        egodriver_version: _common_pb2.VersionId
        sensorsim_version: _common_pb2.VersionId
        physics_version: _common_pb2.VersionId
        traffic_version: _common_pb2.VersionId
        controller_version: _common_pb2.VersionId
        video_model_version: _common_pb2.VersionId
        def __init__(self, runtime_version: _Optional[_Union[_common_pb2.VersionId, _Mapping]] = ..., egodriver_version: _Optional[_Union[_common_pb2.VersionId, _Mapping]] = ..., sensorsim_version: _Optional[_Union[_common_pb2.VersionId, _Mapping]] = ..., physics_version: _Optional[_Union[_common_pb2.VersionId, _Mapping]] = ..., traffic_version: _Optional[_Union[_common_pb2.VersionId, _Mapping]] = ..., controller_version: _Optional[_Union[_common_pb2.VersionId, _Mapping]] = ..., video_model_version: _Optional[_Union[_common_pb2.VersionId, _Mapping]] = ...) -> None: ...
    class SessionMetadata(_message.Message):
        __slots__ = ("session_uuid", "scene_id", "batch_size", "n_sim_steps", "start_timestamp_us", "control_timestep_us", "nre_runid", "nre_version", "nre_uuid")
        SESSION_UUID_FIELD_NUMBER: _ClassVar[int]
        SCENE_ID_FIELD_NUMBER: _ClassVar[int]
        BATCH_SIZE_FIELD_NUMBER: _ClassVar[int]
        N_SIM_STEPS_FIELD_NUMBER: _ClassVar[int]
        START_TIMESTAMP_US_FIELD_NUMBER: _ClassVar[int]
        CONTROL_TIMESTEP_US_FIELD_NUMBER: _ClassVar[int]
        NRE_RUNID_FIELD_NUMBER: _ClassVar[int]
        NRE_VERSION_FIELD_NUMBER: _ClassVar[int]
        NRE_UUID_FIELD_NUMBER: _ClassVar[int]
        session_uuid: str
        scene_id: str
        batch_size: int
        n_sim_steps: int
        start_timestamp_us: int
        control_timestep_us: int
        nre_runid: str
        nre_version: str
        nre_uuid: str
        def __init__(self, session_uuid: _Optional[str] = ..., scene_id: _Optional[str] = ..., batch_size: _Optional[int] = ..., n_sim_steps: _Optional[int] = ..., start_timestamp_us: _Optional[int] = ..., control_timestep_us: _Optional[int] = ..., nre_runid: _Optional[str] = ..., nre_version: _Optional[str] = ..., nre_uuid: _Optional[str] = ...) -> None: ...
    class ActorDefinitions(_message.Message):
        __slots__ = ("actor_aabb",)
        class ActorAABB(_message.Message):
            __slots__ = ("actor_id", "aabb", "actor_label")
            ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
            AABB_FIELD_NUMBER: _ClassVar[int]
            ACTOR_LABEL_FIELD_NUMBER: _ClassVar[int]
            actor_id: str
            aabb: _common_pb2.AABB
            actor_label: str
            def __init__(self, actor_id: _Optional[str] = ..., aabb: _Optional[_Union[_common_pb2.AABB, _Mapping]] = ..., actor_label: _Optional[str] = ...) -> None: ...
        ACTOR_AABB_FIELD_NUMBER: _ClassVar[int]
        actor_aabb: _containers.RepeatedCompositeFieldContainer[RolloutMetadata.ActorDefinitions.ActorAABB]
        def __init__(self, actor_aabb: _Optional[_Iterable[_Union[RolloutMetadata.ActorDefinitions.ActorAABB, _Mapping]]] = ...) -> None: ...
    SESSION_METADATA_FIELD_NUMBER: _ClassVar[int]
    ACTOR_DEFINITIONS_FIELD_NUMBER: _ClassVar[int]
    FORCE_GT_DURATION_FIELD_NUMBER: _ClassVar[int]
    VERSION_IDS_FIELD_NUMBER: _ClassVar[int]
    ROLLOUT_INDEX_FIELD_NUMBER: _ClassVar[int]
    TRANSFORM_EGO_COORDS_RIG_TO_AABB_FIELD_NUMBER: _ClassVar[int]
    EGO_RIG_RECORDED_GROUND_TRUTH_TRAJECTORY_FIELD_NUMBER: _ClassVar[int]
    session_metadata: RolloutMetadata.SessionMetadata
    actor_definitions: RolloutMetadata.ActorDefinitions
    force_gt_duration: int
    version_ids: RolloutMetadata.VersionIds
    rollout_index: int
    transform_ego_coords_rig_to_aabb: _common_pb2.Pose
    ego_rig_recorded_ground_truth_trajectory: _common_pb2.Trajectory
    def __init__(self, session_metadata: _Optional[_Union[RolloutMetadata.SessionMetadata, _Mapping]] = ..., actor_definitions: _Optional[_Union[RolloutMetadata.ActorDefinitions, _Mapping]] = ..., force_gt_duration: _Optional[int] = ..., version_ids: _Optional[_Union[RolloutMetadata.VersionIds, _Mapping]] = ..., rollout_index: _Optional[int] = ..., transform_ego_coords_rig_to_aabb: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ..., ego_rig_recorded_ground_truth_trajectory: _Optional[_Union[_common_pb2.Trajectory, _Mapping]] = ...) -> None: ...

class ActorPoses(_message.Message):
    __slots__ = ("timestamp_us", "actor_poses")
    class ActorPose(_message.Message):
        __slots__ = ("actor_id", "actor_pose")
        ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
        ACTOR_POSE_FIELD_NUMBER: _ClassVar[int]
        actor_id: str
        actor_pose: _common_pb2.Pose
        def __init__(self, actor_id: _Optional[str] = ..., actor_pose: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ...) -> None: ...
    TIMESTAMP_US_FIELD_NUMBER: _ClassVar[int]
    ACTOR_POSES_FIELD_NUMBER: _ClassVar[int]
    timestamp_us: int
    actor_poses: _containers.RepeatedCompositeFieldContainer[ActorPoses.ActorPose]
    def __init__(self, timestamp_us: _Optional[int] = ..., actor_poses: _Optional[_Iterable[_Union[ActorPoses.ActorPose, _Mapping]]] = ...) -> None: ...

class LogEntry(_message.Message):
    __slots__ = ("rollout_metadata", "actor_poses", "render_request", "driver_request", "driver_return", "traffic_request", "traffic_return", "physics_request", "physics_return", "driver_session_request", "driver_camera_image", "driver_ego_trajectory", "traffic_session_request", "controller_request", "controller_return", "egomotion_estimate_error", "route_request", "ground_truth_request", "available_cameras_request", "available_cameras_return", "aggregated_render_request", "available_ego_masks_request", "available_ego_masks_return", "video_model_session_request", "video_model_session_id", "video_model_session_close_request", "video_model_chunk_request", "video_model_chunk_return")
    ROLLOUT_METADATA_FIELD_NUMBER: _ClassVar[int]
    ACTOR_POSES_FIELD_NUMBER: _ClassVar[int]
    RENDER_REQUEST_FIELD_NUMBER: _ClassVar[int]
    DRIVER_REQUEST_FIELD_NUMBER: _ClassVar[int]
    DRIVER_RETURN_FIELD_NUMBER: _ClassVar[int]
    TRAFFIC_REQUEST_FIELD_NUMBER: _ClassVar[int]
    TRAFFIC_RETURN_FIELD_NUMBER: _ClassVar[int]
    PHYSICS_REQUEST_FIELD_NUMBER: _ClassVar[int]
    PHYSICS_RETURN_FIELD_NUMBER: _ClassVar[int]
    DRIVER_SESSION_REQUEST_FIELD_NUMBER: _ClassVar[int]
    DRIVER_CAMERA_IMAGE_FIELD_NUMBER: _ClassVar[int]
    DRIVER_EGO_TRAJECTORY_FIELD_NUMBER: _ClassVar[int]
    TRAFFIC_SESSION_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CONTROLLER_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CONTROLLER_RETURN_FIELD_NUMBER: _ClassVar[int]
    EGOMOTION_ESTIMATE_ERROR_FIELD_NUMBER: _ClassVar[int]
    ROUTE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    GROUND_TRUTH_REQUEST_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_CAMERAS_REQUEST_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_CAMERAS_RETURN_FIELD_NUMBER: _ClassVar[int]
    AGGREGATED_RENDER_REQUEST_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_EGO_MASKS_REQUEST_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_EGO_MASKS_RETURN_FIELD_NUMBER: _ClassVar[int]
    VIDEO_MODEL_SESSION_REQUEST_FIELD_NUMBER: _ClassVar[int]
    VIDEO_MODEL_SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    VIDEO_MODEL_SESSION_CLOSE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    VIDEO_MODEL_CHUNK_REQUEST_FIELD_NUMBER: _ClassVar[int]
    VIDEO_MODEL_CHUNK_RETURN_FIELD_NUMBER: _ClassVar[int]
    rollout_metadata: RolloutMetadata
    actor_poses: ActorPoses
    render_request: _sensorsim_pb2.RGBRenderRequest
    driver_request: _egodriver_pb2.DriveRequest
    driver_return: _egodriver_pb2.DriveResponse
    traffic_request: _traffic_pb2.TrafficRequest
    traffic_return: _traffic_pb2.TrafficReturn
    physics_request: _physics_pb2.PhysicsGroundIntersectionRequest
    physics_return: _physics_pb2.PhysicsGroundIntersectionReturn
    driver_session_request: _egodriver_pb2.DriveSessionRequest
    driver_camera_image: _egodriver_pb2.RolloutCameraImage
    driver_ego_trajectory: _egodriver_pb2.RolloutEgoTrajectory
    traffic_session_request: _traffic_pb2.TrafficSessionRequest
    controller_request: _controller_pb2.RunControllerAndVehicleModelRequest
    controller_return: _controller_pb2.RunControllerAndVehicleModelResponse
    egomotion_estimate_error: _common_pb2.PoseAtTime
    route_request: _egodriver_pb2.RouteRequest
    ground_truth_request: _egodriver_pb2.GroundTruthRequest
    available_cameras_request: _sensorsim_pb2.AvailableCamerasRequest
    available_cameras_return: _sensorsim_pb2.AvailableCamerasReturn
    aggregated_render_request: _sensorsim_pb2.AggregatedRenderRequest
    available_ego_masks_request: _common_pb2.Empty
    available_ego_masks_return: _sensorsim_pb2.AvailableEgoMasksReturn
    video_model_session_request: _video_model_pb2.SessionRequest
    video_model_session_id: _video_model_pb2.SessionId
    video_model_session_close_request: _video_model_pb2.SessionCloseRequest
    video_model_chunk_request: _video_model_pb2.VideoChunkRequest
    video_model_chunk_return: _video_model_pb2.VideoChunkReturn
    def __init__(self, rollout_metadata: _Optional[_Union[RolloutMetadata, _Mapping]] = ..., actor_poses: _Optional[_Union[ActorPoses, _Mapping]] = ..., render_request: _Optional[_Union[_sensorsim_pb2.RGBRenderRequest, _Mapping]] = ..., driver_request: _Optional[_Union[_egodriver_pb2.DriveRequest, _Mapping]] = ..., driver_return: _Optional[_Union[_egodriver_pb2.DriveResponse, _Mapping]] = ..., traffic_request: _Optional[_Union[_traffic_pb2.TrafficRequest, _Mapping]] = ..., traffic_return: _Optional[_Union[_traffic_pb2.TrafficReturn, _Mapping]] = ..., physics_request: _Optional[_Union[_physics_pb2.PhysicsGroundIntersectionRequest, _Mapping]] = ..., physics_return: _Optional[_Union[_physics_pb2.PhysicsGroundIntersectionReturn, _Mapping]] = ..., driver_session_request: _Optional[_Union[_egodriver_pb2.DriveSessionRequest, _Mapping]] = ..., driver_camera_image: _Optional[_Union[_egodriver_pb2.RolloutCameraImage, _Mapping]] = ..., driver_ego_trajectory: _Optional[_Union[_egodriver_pb2.RolloutEgoTrajectory, _Mapping]] = ..., traffic_session_request: _Optional[_Union[_traffic_pb2.TrafficSessionRequest, _Mapping]] = ..., controller_request: _Optional[_Union[_controller_pb2.RunControllerAndVehicleModelRequest, _Mapping]] = ..., controller_return: _Optional[_Union[_controller_pb2.RunControllerAndVehicleModelResponse, _Mapping]] = ..., egomotion_estimate_error: _Optional[_Union[_common_pb2.PoseAtTime, _Mapping]] = ..., route_request: _Optional[_Union[_egodriver_pb2.RouteRequest, _Mapping]] = ..., ground_truth_request: _Optional[_Union[_egodriver_pb2.GroundTruthRequest, _Mapping]] = ..., available_cameras_request: _Optional[_Union[_sensorsim_pb2.AvailableCamerasRequest, _Mapping]] = ..., available_cameras_return: _Optional[_Union[_sensorsim_pb2.AvailableCamerasReturn, _Mapping]] = ..., aggregated_render_request: _Optional[_Union[_sensorsim_pb2.AggregatedRenderRequest, _Mapping]] = ..., available_ego_masks_request: _Optional[_Union[_common_pb2.Empty, _Mapping]] = ..., available_ego_masks_return: _Optional[_Union[_sensorsim_pb2.AvailableEgoMasksReturn, _Mapping]] = ..., video_model_session_request: _Optional[_Union[_video_model_pb2.SessionRequest, _Mapping]] = ..., video_model_session_id: _Optional[_Union[_video_model_pb2.SessionId, _Mapping]] = ..., video_model_session_close_request: _Optional[_Union[_video_model_pb2.SessionCloseRequest, _Mapping]] = ..., video_model_chunk_request: _Optional[_Union[_video_model_pb2.VideoChunkRequest, _Mapping]] = ..., video_model_chunk_return: _Optional[_Union[_video_model_pb2.VideoChunkReturn, _Mapping]] = ...) -> None: ...
