"""In-process contract tests for the SensorsimService servicer (all 8 RPCs),
using the synthetic backend - no CARLA, no network assumptions beyond
loopback."""

import io

import grpc
import pytest
from PIL import Image

from alpasim_carla import GRPC_API_VERSION
from alpasim_carla._proto.alpasim_grpc.v0 import (
    common_pb2,
    sensorsim_pb2,
    sensorsim_pb2_grpc,
)
from alpasim_carla.scenes import ActorDef, SceneCamera, SceneManifest
from alpasim_carla.server import ServerOptions, SyntheticBackend, build_server


def make_manifest(scene_id="carla-town10-demo"):
    spec = sensorsim_pb2.CameraSpec(
        logical_id="camera_front_wide_120fov", resolution_w=1920, resolution_h=1080,
        shutter_type=sensorsim_pb2.ShutterType.GLOBAL,
    )
    spec.opencv_pinhole_param.focal_length_x = 960.0
    spec.opencv_pinhole_param.focal_length_y = 960.0
    spec.opencv_pinhole_param.principal_point_x = 960.0
    spec.opencv_pinhole_param.principal_point_y = 540.0
    pose = common_pb2.Pose()
    pose.vec.x = 1.9
    pose.quat.w, pose.quat.x, pose.quat.y, pose.quat.z = 0.5, -0.5, 0.5, -0.5
    manifest = SceneManifest(scene_id=scene_id, carla_map="Town10HD_Opt")
    manifest.cameras.append(
        SceneCamera(logical_id=spec.logical_id, spec=spec, rig_to_camera=pose)
    )
    manifest.actors["42"] = ActorDef("42", "automobile", (4.0, 1.8, 1.5))
    return manifest


@pytest.fixture()
def stub():
    manifest = make_manifest()
    server, port = build_server(
        {manifest.scene_id: manifest}, SyntheticBackend(), ServerOptions(), port=0,
        host="127.0.0.1",
    )
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    yield sensorsim_pb2_grpc.SensorsimServiceStub(channel)
    channel.close()
    server.stop(grace=None)


def render_request(scene_id="carla-town10-demo", w=512, h=320, fmt=sensorsim_pb2.ImageFormat.JPEG):
    request = sensorsim_pb2.RGBRenderRequest(
        scene_id=scene_id, resolution_w=w, resolution_h=h,
        image_format=fmt, image_quality=95,
    )
    request.camera_intrinsics.logical_id = "camera_front_wide_120fov"
    request.camera_intrinsics.opencv_pinhole_param.focal_length_x = 256.0
    return request


def test_get_version_reports_pinned_api(stub):
    version = stub.get_version(common_pb2.Empty())
    assert "alpasim-carla" in version.version_id
    assert (
        version.grpc_api_version.major,
        version.grpc_api_version.minor,
        version.grpc_api_version.patch,
    ) == GRPC_API_VERSION


def test_get_available_scenes(stub):
    scenes = stub.get_available_scenes(common_pb2.Empty())
    assert list(scenes.scene_ids) == ["carla-town10-demo"]


def test_get_available_cameras(stub):
    cameras = stub.get_available_cameras(
        sensorsim_pb2.AvailableCamerasRequest(scene_id="carla-town10-demo")
    )
    assert [c.logical_id for c in cameras.available_cameras] == [
        "camera_front_wide_120fov"
    ]
    assert cameras.available_cameras[0].rig_to_camera.vec.x == pytest.approx(1.9)


def test_get_available_cameras_unknown_scene_lists_available(stub):
    with pytest.raises(grpc.RpcError) as exc:
        stub.get_available_cameras(sensorsim_pb2.AvailableCamerasRequest(scene_id="nope"))
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    assert "carla-town10-demo" in exc.value.details()


def test_get_available_ego_masks_empty(stub):
    masks = stub.get_available_ego_masks(common_pb2.Empty())
    assert len(masks.ego_mask_metadata) == 0


def test_get_available_trajectories_empty(stub):
    trajectories = stub.get_available_trajectories(
        sensorsim_pb2.AvailableTrajectoriesRequest(scene_id="carla-town10-demo")
    )
    assert len(trajectories.available_trajectories) == 0


def test_render_rgb_jpeg(stub):
    response = stub.render_rgb(render_request())
    image = Image.open(io.BytesIO(response.image_bytes))
    assert image.size == (512, 320)
    assert image.format == "JPEG"


def test_render_rgb_png(stub):
    response = stub.render_rgb(render_request(fmt=sensorsim_pb2.ImageFormat.PNG))
    image = Image.open(io.BytesIO(response.image_bytes))
    assert image.size == (512, 320)
    assert image.format == "PNG"


def test_render_rgb_unknown_scene(stub):
    with pytest.raises(grpc.RpcError) as exc:
        stub.render_rgb(render_request(scene_id="missing-scene"))
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    assert "Available scenes" in exc.value.details()


def test_render_rgb_ego_mask_rejected(stub):
    request = render_request()
    request.insert_ego_mask = True
    request.ego_mask_id.camera_logical_id = "camera_front_wide_120fov"
    with pytest.raises(grpc.RpcError) as exc:
        stub.render_rgb(request)
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "ego mask" in exc.value.details().lower()


def test_render_aggregated(stub):
    agg = sensorsim_pb2.AggregatedRenderRequest()
    agg.rgb_requests.append(render_request())
    agg.rgb_requests.append(render_request(w=256, h=128))
    response = stub.render_aggregated(agg)
    assert len(response.rgb_returns) == 2
    sizes = [
        Image.open(io.BytesIO(r.image_bytes)).size for r in response.rgb_returns
    ]
    assert sizes == [(512, 320), (256, 128)]


def test_render_lidar_synthetic_empty(stub):
    response = stub.render_lidar(
        sensorsim_pb2.LidarRenderRequest(scene_id="carla-town10-demo")
    )
    assert response.num_points == 0
