"""Round-trip test for the .asl reader: write a tiny synthetic log in the
exact format alpasim_utils.logs uses (4-byte big-endian length prefix +
serialized LogEntry), then parse it back."""

import struct

import pytest

from alpasim_carla._proto.alpasim_grpc.v0 import (
    common_pb2,
    logging_pb2,
    sensorsim_pb2,
)
from alpasim_carla.aslio import read_sensorsim_log
from alpasim_carla.scenes import manifest_from_asl


def _write_entries(path, entries):
    with open(path, "wb") as f:
        for entry in entries:
            payload = entry.SerializeToString()
            f.write(struct.pack(">L", len(payload)) + payload)


def _make_log(path):
    metadata = logging_pb2.RolloutMetadata()
    metadata.session_metadata.scene_id = "clipgt-test-scene"
    metadata.session_metadata.n_sim_steps = 2
    ego = metadata.actor_definitions.actor_aabb.add()
    ego.actor_id = "EGO"
    ego.aabb.size_x, ego.aabb.size_y, ego.aabb.size_z = 5.3, 2.1, 1.5
    car = metadata.actor_definitions.actor_aabb.add()
    car.actor_id = "42"
    car.actor_label = "automobile"
    car.aabb.size_x, car.aabb.size_y, car.aabb.size_z = 4.0, 1.8, 1.5

    cameras = sensorsim_pb2.AvailableCamerasReturn()
    cam = cameras.available_cameras.add()
    cam.logical_id = "camera_front_wide_120fov"
    cam.intrinsics.logical_id = "camera_front_wide_120fov"
    cam.intrinsics.resolution_w = 1920
    cam.intrinsics.resolution_h = 1080
    cam.intrinsics.opencv_pinhole_param.focal_length_x = 960.0
    cam.intrinsics.opencv_pinhole_param.focal_length_y = 960.0
    cam.intrinsics.opencv_pinhole_param.principal_point_x = 960.0
    cam.intrinsics.opencv_pinhole_param.principal_point_y = 540.0
    cam.rig_to_camera.vec.x = 1.9
    cam.rig_to_camera.quat.w = 0.5
    cam.rig_to_camera.quat.x = -0.5
    cam.rig_to_camera.quat.y = 0.5
    cam.rig_to_camera.quat.z = -0.5

    render = sensorsim_pb2.RGBRenderRequest(
        scene_id="clipgt-test-scene",
        resolution_h=1080,
        resolution_w=1900,
        frame_start_us=1000,
        frame_end_us=31000,
        image_format=sensorsim_pb2.ImageFormat.JPEG,
        image_quality=95,
    )
    render.camera_intrinsics.CopyFrom(cam.intrinsics)
    obj = render.dynamic_objects.add()
    obj.track_id = "42"
    obj.pose_pair.start_pose.vec.x = 10.0

    image = logging_pb2.LogEntry()
    image.driver_camera_image.camera_image.logical_id = "camera_front_wide_120fov"
    image.driver_camera_image.camera_image.frame_start_us = 1000
    image.driver_camera_image.camera_image.image_bytes = b"jpegbytes"

    _write_entries(
        path,
        [
            logging_pb2.LogEntry(rollout_metadata=metadata),
            logging_pb2.LogEntry(available_cameras_return=cameras),
            logging_pb2.LogEntry(render_request=render),
            image,
        ],
    )


def test_read_sensorsim_log(tmp_path):
    path = str(tmp_path / "rollout.asl")
    _make_log(path)
    log = read_sensorsim_log(path, keep_driver_images=True)
    assert log.scene_id == "clipgt-test-scene"
    assert log.entry_counts["render_request"] == 1
    assert len(log.render_requests) == 1
    request = log.render_requests[0]
    assert request.resolution_w == 1900
    assert request.dynamic_objects[0].track_id == "42"
    assert log.available_cameras_return is not None
    assert log.driver_images[("camera_front_wide_120fov", 1000)] == b"jpegbytes"


def test_manifest_from_asl(tmp_path):
    path = str(tmp_path / "rollout.asl")
    _make_log(path)
    manifest = manifest_from_asl(path, carla_map="Town03")
    assert manifest.scene_id == "clipgt-test-scene"
    assert manifest.carla_map == "Town03"
    assert manifest.actors["42"].label == "automobile"
    # proto AABB fields are float32: compare with tolerance
    assert manifest.actors["42"].size_lwh == pytest.approx((4.0, 1.8, 1.5), abs=1e-6)
    assert manifest.cameras[0].logical_id == "camera_front_wide_120fov"
    ret = manifest.available_cameras_return()
    assert ret.available_cameras[0].intrinsics.opencv_pinhole_param.focal_length_x == 960.0
