#!/usr/bin/env python
"""Record a CARLA drive into bridge test fixtures.

Drives the CARLA traffic manager for N ticks on a chosen map, recording ego +
NPC poses each tick, and emits:

  * a scene manifest YAML (actor table with real bbox dims from the spawned
    actors, camera rig = the bundled 4-camera alpamayo-style pinhole rig),
  * a replay fixture .asl-style request log: a length-prefixed LogEntry
    stream containing synthetic RGBRenderRequests that mirror the recorded
    poses (usable by tools/replay_render.py and as test data).

This does NOT produce AlpaSim runtime-side session data (scene catalogs /
recordings); closed-loop scenes reuse AlpaSim's own scene catalog ids - see
PLAN.md scope fences.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alpasim_carla import frames
from alpasim_carla._proto.alpasim_grpc.v0 import (
    common_pb2,
    logging_pb2,
    sensorsim_pb2,
)
from alpasim_carla.scenes import (
    ActorDef,
    SceneCamera,
    SceneManifest,
    manifest_to_yaml,
)

IDEAL_OPTICAL_QUAT = (0.5, -0.5, 0.5, -0.5)


def make_rig():
    """The bundled 4-camera pinhole rig (alpamayo logical ids)."""
    def cam(logical_id, x, y, z, yaw_deg, hfov_deg, w=1920, h=1080):
        half = math.radians(yaw_deg) / 2.0
        yaw_quat = (math.cos(half), 0.0, 0.0, math.sin(half))
        q = frames.quat_multiply(yaw_quat, IDEAL_OPTICAL_QUAT)
        fx = (w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
        spec = sensorsim_pb2.CameraSpec(
            logical_id=logical_id, resolution_w=w, resolution_h=h,
            shutter_type=sensorsim_pb2.ShutterType.GLOBAL,
        )
        spec.opencv_pinhole_param.focal_length_x = fx
        spec.opencv_pinhole_param.focal_length_y = fx
        spec.opencv_pinhole_param.principal_point_x = w / 2.0
        spec.opencv_pinhole_param.principal_point_y = h / 2.0
        pose = common_pb2.Pose(
            vec=common_pb2.Vec3(x=x, y=y, z=z),
            quat=common_pb2.Quat(w=q[0], x=q[1], y=q[2], z=q[3]),
        )
        return SceneCamera(logical_id=logical_id, spec=spec, rig_to_camera=pose)

    return [
        cam("camera_cross_left_120fov", 2.6, 0.9, 0.78, 55.0, 120.0),
        cam("camera_front_wide_120fov", 1.89, -0.06, 1.32, 0.0, 120.0),
        cam("camera_cross_right_120fov", 2.57, -0.92, 0.82, -55.0, 120.0),
        cam("camera_front_tele_30fov", 1.87, -0.11, 1.31, 0.0, 30.0),
    ]


def ue_transform_to_pose(transform) -> common_pb2.Pose:
    vec, quat = frames.alpasim_pose_from_carla(
        (transform.location.x, transform.location.y, transform.location.z),
        (transform.rotation.pitch, transform.rotation.yaw, transform.rotation.roll),
        axes="flu",
    )
    return common_pb2.Pose(
        vec=common_pb2.Vec3(x=vec[0], y=vec[1], z=vec[2]),
        quat=common_pb2.Quat(w=quat[0], x=quat[1], y=quat[2], z=quat[3]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carla-host", default="127.0.0.1")
    parser.add_argument("--carla-port", type=int, required=True)
    parser.add_argument("--map", dest="carla_map", default="Town10HD_Opt")
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--vehicles", type=int, default=12)
    parser.add_argument("--ticks", type=int, default=100)
    parser.add_argument("--tick-seconds", type=float, default=0.1)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    import carla

    client = carla.Client(args.carla_host, args.carla_port)
    client.set_timeout(120)
    world = client.get_world()
    if not world.get_map().name.endswith(args.carla_map):
        world = client.load_world(args.carla_map)
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = args.tick_seconds
    world.apply_settings(settings)
    tm = client.get_trafficmanager(8000)
    tm.set_synchronous_mode(True)

    blueprint_library = world.get_blueprint_library()
    spawn_points = world.get_map().get_spawn_points()
    vehicles = []
    try:
        car_blueprints = [
            bp for bp in blueprint_library.filter("vehicle.*")
            if int(bp.get_attribute("number_of_wheels")) == 4
        ]
        for i, sp in enumerate(spawn_points[: args.vehicles + 1]):
            bp = car_blueprints[i % len(car_blueprints)]
            vehicle = world.try_spawn_actor(bp, sp)
            if vehicle is None:
                continue
            vehicle.set_autopilot(True, tm.get_port())
            vehicles.append(vehicle)
        if not vehicles:
            print("No vehicles spawned; aborting", file=sys.stderr)
            return 1
        ego = vehicles[0]
        print(f"Recording {args.ticks} ticks with {len(vehicles)} vehicles "
              f"(ego={ego.type_id})")

        manifest = SceneManifest(
            scene_id=args.scene_id,
            carla_map=args.carla_map,
            cameras=make_rig(),
            description=f"Recorded with tools/record_scene.py on {args.carla_map}",
        )
        for vehicle in vehicles[1:]:
            extent = vehicle.bounding_box.extent
            manifest.actors[str(vehicle.id)] = ActorDef(
                actor_id=str(vehicle.id),
                label="automobile",
                size_lwh=(2 * extent.x, 2 * extent.y, 2 * extent.z),
            )

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        request_log = out_dir / f"{args.scene_id}.requests.asl"
        rig = manifest.cameras
        t_us = 0
        step_us = int(args.tick_seconds * 1e6)
        with open(request_log, "wb") as log_file:
            for tick in range(args.ticks):
                world.tick()
                t_us += step_us
                ego_pose = ue_transform_to_pose(ego.get_transform())
                # one request per camera per tick, mirroring runtime behavior
                for cam in rig:
                    request = sensorsim_pb2.RGBRenderRequest(
                        scene_id=args.scene_id,
                        resolution_h=cam.spec.resolution_h,
                        resolution_w=cam.spec.resolution_w,
                        frame_start_us=t_us,
                        frame_end_us=t_us + step_us // 3,
                        image_format=sensorsim_pb2.ImageFormat.JPEG,
                        image_quality=95,
                    )
                    request.camera_intrinsics.CopyFrom(cam.spec)
                    # sensor_pose = ego(local->rig) @ rig_to_camera
                    ego_tuple = frames.grpc_pose_to_tuple(ego_pose)
                    cam_tuple = frames.grpc_pose_to_tuple(cam.rig_to_camera)
                    sensor_vec, sensor_quat = frames.compose(ego_tuple, cam_tuple)
                    for pose_field in (request.sensor_pose.start_pose,
                                       request.sensor_pose.end_pose):
                        pose_field.vec.x, pose_field.vec.y, pose_field.vec.z = sensor_vec
                        (pose_field.quat.w, pose_field.quat.x,
                         pose_field.quat.y, pose_field.quat.z) = sensor_quat
                    for vehicle in vehicles[1:]:
                        obj = request.dynamic_objects.add()
                        obj.track_id = str(vehicle.id)
                        center = vehicle.get_transform()
                        pose = ue_transform_to_pose(center)
                        obj.pose_pair.start_pose.CopyFrom(pose)
                        obj.pose_pair.end_pose.CopyFrom(pose)
                    entry = logging_pb2.LogEntry(render_request=request)
                    payload = entry.SerializeToString()
                    log_file.write(struct.pack(">L", len(payload)) + payload)

        manifest_path = out_dir / f"{args.scene_id}.yaml"
        with open(manifest_path, "w") as f:
            f.write(manifest_to_yaml(manifest))
        print(f"Wrote {manifest_path} and {request_log} "
              f"({args.ticks * len(rig)} requests)")
        return 0
    finally:
        for vehicle in vehicles:
            try:
                vehicle.set_autopilot(False)
                vehicle.destroy()
            except RuntimeError:
                pass
        settings = world.get_settings()
        settings.synchronous_mode = False
        settings.fixed_delta_seconds = None
        world.apply_settings(settings)


if __name__ == "__main__":
    raise SystemExit(main())
