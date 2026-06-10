"""Scene packages: the bridge-side description of what a scene_id means.

A scene package is a YAML manifest mapping an AlpaSim scene_id to a CARLA
map plus everything the bridge needs that the render requests do NOT carry:

  * the camera rig (logical ids, intrinsics, rig_to_camera) returned by
    get_available_cameras - the runtime treats the renderer as the source of
    truth for cameras (local config may only *modify* cameras we report, not
    add new ones; verified in alpasim_runtime.camera_catalog at a1f05bb);
  * the actor table (actor/track id -> label + AABB size) used for blueprint
    selection, since DynamicObject carries only track_id + poses;
  * a local_to_world anchor placing the AlpaSim local frame in the town.

For replay workflows the manifest is generated from a rollout.asl
(rollout_metadata has the actor table; available_cameras_return has the rig).
Camera intrinsics may be authored as readable pinhole fields or carried as
base64-serialized CameraSpec protos (exactly what was recorded).
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from alpasim_carla._proto.alpasim_grpc.v0 import common_pb2, sensorsim_pb2
from alpasim_carla.aslio import read_sensorsim_log


@dataclass
class ActorDef:
    actor_id: str
    label: str
    size_lwh: Tuple[float, float, float]  # AABB size_x (length), size_y, size_z


@dataclass
class SceneCamera:
    logical_id: str
    spec: sensorsim_pb2.CameraSpec
    rig_to_camera: common_pb2.Pose


@dataclass
class SceneManifest:
    scene_id: str
    carla_map: str
    cameras: List[SceneCamera] = field(default_factory=list)
    actors: Dict[str, ActorDef] = field(default_factory=dict)
    anchor_translation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    anchor_yaw_deg: float = 0.0
    ground_z: Optional[float] = None
    blueprint_overrides: Dict[str, str] = field(default_factory=dict)  # label -> blueprint
    description: str = ""

    def available_cameras_return(self) -> sensorsim_pb2.AvailableCamerasReturn:
        ret = sensorsim_pb2.AvailableCamerasReturn()
        for cam in self.cameras:
            entry = ret.available_cameras.add()
            entry.intrinsics.CopyFrom(cam.spec)
            entry.rig_to_camera.CopyFrom(cam.rig_to_camera)
            entry.logical_id = cam.logical_id
        return ret


class UnknownSceneError(KeyError):
    """Raised for a scene_id the bridge has no manifest for.

    Message lists the available scenes - surfaced as gRPC NOT_FOUND detail.
    """

    def __init__(self, scene_id: str, available: List[str]):
        super().__init__(scene_id)
        self.scene_id = scene_id
        self.available = sorted(available)

    def __str__(self) -> str:
        return (
            f"Unknown scene_id {self.scene_id!r}. Available scenes: "
            f"{self.available}. Add a scene manifest (scenes/) or generate one "
            f"from a rollout log with `alpasim-carla scene-from-asl`."
        )


# ---------------------------------------------------------------------------
# YAML (de)serialization
# ---------------------------------------------------------------------------


def _pose_to_yaml(pose: common_pb2.Pose) -> dict:
    return {
        "translation": [pose.vec.x, pose.vec.y, pose.vec.z],
        "quat_wxyz": [pose.quat.w, pose.quat.x, pose.quat.y, pose.quat.z],
    }


def _pose_from_yaml(data: dict) -> common_pb2.Pose:
    t = data["translation"]
    q = data["quat_wxyz"]
    return common_pb2.Pose(
        vec=common_pb2.Vec3(x=t[0], y=t[1], z=t[2]),
        quat=common_pb2.Quat(w=q[0], x=q[1], y=q[2], z=q[3]),
    )


def _spec_from_yaml(data: dict) -> sensorsim_pb2.CameraSpec:
    if "proto_b64" in data:
        spec = sensorsim_pb2.CameraSpec()
        spec.ParseFromString(base64.b64decode(data["proto_b64"]))
        return spec
    model = data["model"]
    if model != "opencv_pinhole":
        raise ValueError(
            f"Authored camera model {model!r} not supported; use 'opencv_pinhole' "
            "or embed a recorded spec as proto_b64."
        )
    spec = sensorsim_pb2.CameraSpec(
        logical_id=data.get("logical_id", ""),
        resolution_h=int(data["height"]),
        resolution_w=int(data["width"]),
        shutter_type=sensorsim_pb2.ShutterType.GLOBAL,
    )
    spec.opencv_pinhole_param.focal_length_x = float(data["fx"])
    spec.opencv_pinhole_param.focal_length_y = float(data.get("fy", data["fx"]))
    spec.opencv_pinhole_param.principal_point_x = float(
        data.get("cx", float(data["width"]) / 2.0)
    )
    spec.opencv_pinhole_param.principal_point_y = float(
        data.get("cy", float(data["height"]) / 2.0)
    )
    return spec


def _spec_to_yaml(spec: sensorsim_pb2.CameraSpec) -> dict:
    if spec.WhichOneof("camera_param") == "opencv_pinhole_param":
        p = spec.opencv_pinhole_param
        if not (any(p.radial_coeffs) or any(p.tangential_coeffs) or any(p.thin_prism_coeffs)):
            return {
                "model": "opencv_pinhole",
                "logical_id": spec.logical_id,
                "width": spec.resolution_w,
                "height": spec.resolution_h,
                "fx": p.focal_length_x,
                "fy": p.focal_length_y,
                "cx": p.principal_point_x,
                "cy": p.principal_point_y,
            }
    return {
        "model": spec.WhichOneof("camera_param") or "unset",
        "logical_id": spec.logical_id,
        "proto_b64": base64.b64encode(spec.SerializeToString()).decode("ascii"),
    }


def manifest_to_yaml(manifest: SceneManifest) -> str:
    data = {
        "scene_id": manifest.scene_id,
        "carla_map": manifest.carla_map,
        "description": manifest.description,
        "local_to_world": {
            "translation": list(manifest.anchor_translation),
            "yaw_deg": manifest.anchor_yaw_deg,
        },
        "ground_z": manifest.ground_z,
        "blueprint_overrides": manifest.blueprint_overrides,
        "cameras": [
            {
                "logical_id": cam.logical_id,
                "rig_to_camera": _pose_to_yaml(cam.rig_to_camera),
                "intrinsics": _spec_to_yaml(cam.spec),
            }
            for cam in manifest.cameras
        ],
        "actors": [
            {
                "actor_id": a.actor_id,
                "label": a.label,
                "size_lwh": list(a.size_lwh),
            }
            for a in manifest.actors.values()
        ],
    }
    return yaml.safe_dump(data, sort_keys=False)


def manifest_from_yaml(text: str) -> SceneManifest:
    data = yaml.safe_load(text)
    anchor = data.get("local_to_world") or {}
    manifest = SceneManifest(
        scene_id=data["scene_id"],
        carla_map=data["carla_map"],
        anchor_translation=tuple(anchor.get("translation", (0.0, 0.0, 0.0))),
        anchor_yaw_deg=float(anchor.get("yaw_deg", 0.0)),
        ground_z=data.get("ground_z"),
        blueprint_overrides=dict(data.get("blueprint_overrides") or {}),
        description=data.get("description", ""),
    )
    for cam in data.get("cameras", []):
        spec = _spec_from_yaml(cam["intrinsics"])
        if not spec.logical_id:
            spec.logical_id = cam["logical_id"]
        manifest.cameras.append(
            SceneCamera(
                logical_id=cam["logical_id"],
                spec=spec,
                rig_to_camera=_pose_from_yaml(cam["rig_to_camera"]),
            )
        )
    for actor in data.get("actors", []):
        adef = ActorDef(
            actor_id=str(actor["actor_id"]),
            label=actor.get("label", ""),
            size_lwh=tuple(actor.get("size_lwh", (4.5, 1.9, 1.6))),
        )
        manifest.actors[adef.actor_id] = adef
    return manifest


def load_scene_dir(path: str) -> Dict[str, SceneManifest]:
    scenes: Dict[str, SceneManifest] = {}
    for f in sorted(Path(path).glob("*.yaml")):
        manifest = manifest_from_yaml(f.read_text())
        if manifest.scene_id in scenes:
            raise ValueError(f"Duplicate scene_id {manifest.scene_id!r} in {f}")
        scenes[manifest.scene_id] = manifest
    return scenes


# ---------------------------------------------------------------------------
# Manifest generation from a rollout log
# ---------------------------------------------------------------------------


def manifest_from_asl(
    asl_path: str,
    carla_map: str = "Town10HD_Opt",
    anchor_translation: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    anchor_yaw_deg: float = 0.0,
) -> SceneManifest:
    """Build a scene manifest from a recorded rollout.

    Cameras come from the recorded available_cameras_return (so the bridge
    serves exactly the rig the runtime saw); the actor table comes from
    rollout_metadata.actor_definitions (the only place AlpaSim states bbox
    dims and labels).
    """
    log = read_sensorsim_log(asl_path)
    if log.rollout_metadata is None:
        raise ValueError(f"{asl_path} contains no rollout_metadata; not a rollout log?")
    manifest = SceneManifest(
        scene_id=log.scene_id,
        carla_map=carla_map,
        anchor_translation=anchor_translation,
        anchor_yaw_deg=anchor_yaw_deg,
        description=f"Generated from {asl_path}",
    )
    if log.available_cameras_return is not None:
        for cam in log.available_cameras_return.available_cameras:
            spec = sensorsim_pb2.CameraSpec()
            spec.CopyFrom(cam.intrinsics)
            pose = common_pb2.Pose()
            pose.CopyFrom(cam.rig_to_camera)
            manifest.cameras.append(
                SceneCamera(logical_id=cam.logical_id, spec=spec, rig_to_camera=pose)
            )
    for actor in log.rollout_metadata.actor_definitions.actor_aabb:
        manifest.actors[actor.actor_id] = ActorDef(
            actor_id=actor.actor_id,
            label=actor.actor_label,
            size_lwh=(actor.aabb.size_x, actor.aabb.size_y, actor.aabb.size_z),
        )
    return manifest
