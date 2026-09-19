"""Scene packages: the bridge-side description of what a scene_id means.

A scene package is a YAML manifest mapping an AlpaSim scene_id to a CARLA
map plus everything the bridge needs that the render requests do NOT carry:

  * the camera rig (logical ids, intrinsics, rig_to_camera) returned by
    get_available_cameras - the runtime treats the renderer as the source of
    truth for cameras (local config may only *modify* cameras we report, not
    add new ones; verified in alpasim_runtime.camera_catalog at a1f05bb);
  * the actor table (actor/track id -> label + AABB size) used for blueprint
    selection, since DynamicObject carries only track_id + poses;
  * a local_to_world anchor placing the AlpaSim local frame in the town;
  * ``traffic:`` - what was on the road, in simforge-closed-loop's run
    manifest vocabulary, because the actor table says what the clip HAD and
    a suppressed run contains none of it.

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


#: What was on the road, in the words ``simforge-closed-loop``'s run manifest
#: uses (``tools/run_manifest.py:TRAFFIC_SOURCES``). Copied verbatim, not
#: paraphrased: the run manifest and the scene manifest are two documents
#: describing one run, and a run that is ``clip_replay_suppressed`` in one
#: and "suppressed" or "none" in the other is a run whose two records have
#: to be reconciled by a human who was not there.
#:
#: * ``clip_replay`` - the recording's own actors were replayed as traffic.
#:   ``scenes/g3`` is this: the 0.9.16 rehearsal carried the clip's traffic.
#: * ``clip_replay_suppressed`` - the clip had actors and the run contained
#:   none of them (``SimulationConfig.replayed_traffic: disabled``). The
#:   Belmont rerun is this, and the manifest's ``actors:`` table still
#:   carries the clip's sizes: the table says what the clip HAD, this field
#:   says what the run CONTAINED, and after the 2026-09-19 campaign those
#:   are not the same question.
#: * ``scripted`` - the actors came from a scene package rather than from a
#:   recording. ``scenes/examples`` is this: authored render fixtures with
#:   no clip behind them.
TRAFFIC_SOURCES = ("clip_replay", "clip_replay_suppressed", "scripted")


class TrafficContradiction(RuntimeError):
    """The world contains traffic the scene manifest said it would not.

    Raised out of ``ActorRegistry.sync`` rather than logged, because a run
    that declares ``clip_replay_suppressed`` and then replays the clip is a
    run whose evidence says the opposite of what happened - and both halves
    look normal afterwards.
    """


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
    # CARLA build this scene was recorded against ("0.9.16", "0.10.0", or a
    # git hash for a custom build). None means "do not check". The bridge
    # refuses to start against a server that does not match.
    carla_version: Optional[str] = None
    # What was on the road: one of TRAFFIC_SOURCES. Required of a manifest on
    # disk (see _require_traffic); None is reachable only in memory, where
    # dozens of tests build a SceneManifest with no file behind it.
    traffic: Optional[str] = None

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
    after_map = {}
    if manifest.carla_version:
        # Insert after carla_map so the two server-facing keys sit together.
        after_map["carla_version"] = manifest.carla_version
    if manifest.traffic:
        after_map["traffic"] = manifest.traffic
    if after_map:
        ordered = {}
        for key, value in data.items():
            ordered[key] = value
            if key == "carla_map":
                ordered.update(after_map)
        data = ordered
    return yaml.safe_dump(data, sort_keys=False)


def _require_carla_version(data: Dict[str, object]) -> str:
    """A handshake that runs only when the field is present is an opt-in.

    ``compat.py`` computes the expected server version from the manifests
    that declare one, and a scene that omits the field *abstains* - which
    was written so one versioned manifest could speak for a directory. What
    it meant in practice is that a manifest could skip the check by saying
    nothing, and the one scene Stage C actually loads had done exactly that
    while the three render-test manifests all declared theirs.

    So the field is required at load. Abstention across a directory still
    works - every scene declares the same version and ``expected_version``
    collapses the set - and ``--expect-carla-version ''`` still skips the
    check deliberately, which is the difference between an override and an
    omission.
    """
    version = data.get("carla_version")
    if isinstance(version, str) and version.strip():
        return version
    raise ValueError(
        f"scene {data.get('scene_id')!r} declares no carla_version. It is the "
        f"build this scene's anchor and map name were recorded against, and "
        f"compat.py checks the server against it - so omitting it does not "
        f"relax the handshake, it skips it. Add the server's version "
        f'(e.g. carla_version: "0.9.16"), or pass --expect-carla-version "" '
        f"to skip the check for a run that means to."
    )


def _require_traffic(data: Dict[str, object]) -> str:
    """Required, for the reason ``carla_version`` is: it gates a check.

    ``ActorRegistry.sync`` holds a scene that declares
    ``clip_replay_suppressed`` to that claim - an empty road is the one
    traffic statement the bridge can verify, since it is the only process
    that sees the actors. A field that can be omitted is a way to skip that
    verification while looking like a manifest that simply predates the
    field, which is exactly what ``carla_version`` did before it was
    required: "a handshake that runs only when the field is present is an
    opt-in".

    It is also the scene's half of a record. ``simforge-closed-loop``'s run
    manifest already refuses a run that does not state its ``traffic``, and
    derives the value from the experiment config - from the run's INTENT.
    This field is the same word written down where the actors actually
    arrive. The Belmont campaign that collided on seed 20260918 recorded
    nothing about what was on the road, and establishing it afterwards meant
    counting actor poses in the log.

    Every shipped manifest can answer it, which is the test of whether a
    required field is the right shape: ``scenes/g3`` carried the clip's
    traffic (``clip_replay``), ``scenes/belmont`` is the suppressed rerun
    (``clip_replay_suppressed``), and ``scenes/examples`` are authored render
    fixtures with no recording behind them (``scripted``).
    """
    traffic = data.get("traffic")
    if isinstance(traffic, str) and traffic.strip() in TRAFFIC_SOURCES:
        return traffic.strip()
    # `traffic: true` and `traffic: none` are YAML scalars, not strings, and
    # both are words a reasonable person reaches for. They get the
    # vocabulary, not the "you said nothing" message.
    if traffic is not None and str(traffic).strip():
        raise ValueError(
            f"scene {data.get('scene_id')!r} declares traffic="
            f"{str(traffic).strip()!r}, which is not one of {TRAFFIC_SOURCES}. The "
            f"vocabulary is simforge-closed-loop's run manifest "
            f"(tools/run_manifest.py:TRAFFIC_SOURCES), copied verbatim so the "
            f"two documents describing one run use one word for one thing."
        )
    raise ValueError(
        f"scene {data.get('scene_id')!r} declares no traffic. It says what "
        f"was ON THE ROAD - the clip's recorded actors replayed "
        f"('clip_replay'), deliberately not replayed "
        f"('clip_replay_suppressed'), or a scene package's own actors "
        f"('scripted') - and the bridge checks a suppressed scene against "
        f"the actors it is actually asked to spawn, so omitting the field "
        f"does not relax that check, it skips it. It is also the scene's "
        f"half of the run manifest's `traffic` field: a run that does not "
        f"say is one whose road can only be established by counting actors "
        f"in its log, where an empty road and actors lost to a defect look "
        f"the same. Add one of {TRAFFIC_SOURCES}."
    )


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
        carla_version=_require_carla_version(data),
        traffic=_require_traffic(data),
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

    ``traffic`` is ``clip_replay``: the actors in the generated table are the
    recording's own, and a manifest generated from a log describes the run
    that log came from. Suppression is a decision about a LATER run, so
    whoever makes it edits the field - the way scenes/belmont did.
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
        traffic="clip_replay",
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
