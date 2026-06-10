"""Track-id -> CARLA actor registry: the bridge's ONLY cross-call memory.

Semantics (docs/CONTRACT.md):
  * unseen track_id in a request  -> spawn an actor (blueprint chosen from the
    scene's actor table: label + AABB dims; documented fallback ladder ends in
    a plain box prop - an object is NEVER silently dropped),
  * known track_id                -> teleport (actor.set_transform),
  * track_id absent from request  -> despawn.

All bridge-managed actors have physics disabled - AlpaSim owns motion; CARLA
only poses puppets. AlpaSim object poses are local->aabb (bounding-box
CENTER); CARLA transforms place the actor pivot, so we compensate with
actor.bounding_box.location per blueprint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from alpasim_carla import frames
from alpasim_carla.scenes import ActorDef, SceneManifest

logger = logging.getLogger("alpasim_carla.registry")

# Curated CARLA 0.9.16 blueprint dimensions (length, width, height in meters,
# approximate stock values) used for nearest-dims selection. Kept small and
# documented on purpose; scene manifests can override per label via
# blueprint_overrides.
VEHICLE_BLUEPRINTS: List[Tuple[str, Tuple[float, float, float]]] = [
    ("vehicle.mini.cooper_s", (3.80, 1.92, 1.45)),
    ("vehicle.audi.tt", (4.18, 1.99, 1.39)),
    ("vehicle.tesla.model3", (4.69, 2.09, 1.49)),
    ("vehicle.mercedes.coupe_2020", (4.79, 2.04, 1.45)),
    ("vehicle.audi.etron", (4.90, 2.03, 1.62)),
    ("vehicle.nissan.patrol_2021", (5.08, 2.18, 1.93)),
    ("vehicle.ford.ambulance", (6.34, 2.39, 2.55)),
    ("vehicle.carlamotors.firetruck", (8.49, 2.94, 3.41)),
]
TWO_WHEELER_BLUEPRINTS: List[Tuple[str, Tuple[float, float, float]]] = [
    ("vehicle.diamondback.century", (1.66, 0.42, 1.04)),
    ("vehicle.yamaha.yzf", (2.19, 0.81, 1.16)),
]
WALKER_BLUEPRINT = "walker.pedestrian.0001"
FALLBACK_BOX_BLUEPRINT = "static.prop.box03"

# Scene-label vocabulary observed in AlpaSim actor_definitions plus common
# synonyms. Unknown labels fall through to dims-based heuristics, then the
# box prop - with a structured warning either way.
_VEHICLE_LABELS = {"automobile", "vehicle", "car", "truck", "bus", "trailer", "van"}
_TWO_WHEELER_LABELS = {"cyclist", "bicycle", "motorcycle", "rider", "moped"}
_WALKER_LABELS = {"pedestrian", "person", "human", "walker"}


def _nearest_by_dims(
    candidates: List[Tuple[str, Tuple[float, float, float]]],
    size_lwh: Tuple[float, float, float],
) -> str:
    length, width, _ = size_lwh
    best = min(
        candidates,
        key=lambda c: (c[1][0] - length) ** 2 + (c[1][1] - width) ** 2,
    )
    return best[0]


def choose_blueprint(
    track_id: str, actor_def: Optional[ActorDef], scene: SceneManifest
) -> Tuple[str, str]:
    """Returns (blueprint_id, decision) where decision is a structured note.

    Fallback ladder: manifest blueprint_overrides[label] -> category table by
    label -> dims heuristic -> box prop. Never raises, never skips.
    """
    label = (actor_def.label if actor_def else "").strip().lower()
    size = actor_def.size_lwh if actor_def else (4.5, 1.9, 1.6)

    if label and label in scene.blueprint_overrides:
        return scene.blueprint_overrides[label], f"override[{label}]"
    if label in _VEHICLE_LABELS:
        return _nearest_by_dims(VEHICLE_BLUEPRINTS, size), f"vehicle[{label}]"
    if label in _TWO_WHEELER_LABELS:
        return _nearest_by_dims(TWO_WHEELER_BLUEPRINTS, size), f"two_wheeler[{label}]"
    if label in _WALKER_LABELS:
        return WALKER_BLUEPRINT, f"walker[{label}]"

    # Unknown / missing label: dims heuristic, then the documented box prop.
    length, width, height = size
    if 2.5 < length < 13.0 and 1.3 < width < 3.2:
        blueprint = _nearest_by_dims(VEHICLE_BLUEPRINTS, size)
        logger.warning(
            "blueprint_fallback track_id=%s label=%r dims=%.2fx%.2fx%.2f -> %s "
            "(car-like dims heuristic; add the label to the scene manifest "
            "blueprint_overrides to silence)",
            track_id, label, length, width, height, blueprint,
        )
        return blueprint, f"dims_heuristic[{label or 'no-label'}]"
    if length < 1.2 and height > 1.2:
        logger.warning(
            "blueprint_fallback track_id=%s label=%r dims=%.2fx%.2fx%.2f -> %s "
            "(person-like dims heuristic)",
            track_id, label, length, width, height, WALKER_BLUEPRINT,
        )
        return WALKER_BLUEPRINT, f"dims_heuristic_walker[{label or 'no-label'}]"
    logger.warning(
        "blueprint_fallback track_id=%s label=%r dims=%.2fx%.2fx%.2f -> %s "
        "(documented plain-box fallback; object NOT dropped)",
        track_id, label, length, width, height, FALLBACK_BOX_BLUEPRINT,
    )
    return FALLBACK_BOX_BLUEPRINT, f"box_fallback[{label or 'no-label'}]"


@dataclass
class ManagedActor:
    track_id: str
    actor: object  # carla.Actor
    blueprint_id: str
    decision: str
    bbox_offset_ue: Tuple[float, float, float]


class ActorRegistry:
    def __init__(self, carla_module, world, scene: SceneManifest):
        self._carla = carla_module
        self._world = world
        self._scene = scene
        self._actors: Dict[str, ManagedActor] = {}
        self._blueprints = world.get_blueprint_library()
        self._spawn_counter = 0

    @property
    def actor_count(self) -> int:
        return len(self._actors)

    def transforms(self) -> Dict[str, Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
        """track_id -> ((x,y,z), (pitch,yaw,roll)) as reported by CARLA."""
        out = {}
        for track_id, managed in self._actors.items():
            tf = managed.actor.get_transform()
            out[track_id] = (
                (tf.location.x, tf.location.y, tf.location.z),
                (tf.rotation.pitch, tf.rotation.yaw, tf.rotation.roll),
            )
        return out

    def _spawn(self, track_id: str, transform) -> ManagedActor:
        actor_def = self._scene.actors.get(track_id)
        blueprint_id, decision = choose_blueprint(track_id, actor_def, self._scene)
        try:
            blueprint = self._blueprints.find(blueprint_id)
        except (IndexError, RuntimeError):
            logger.warning(
                "blueprint %s missing in this CARLA build; using %s",
                blueprint_id, FALLBACK_BOX_BLUEPRINT,
            )
            blueprint_id, decision = FALLBACK_BOX_BLUEPRINT, decision + "+missing_bp"
            blueprint = self._blueprints.find(blueprint_id)
        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute("role_name", f"alpasim_{track_id}")

        # The spawn position is irrelevant - the actor is teleported to its
        # exact target right after (and on every subsequent request). But the
        # initial spawn DOES collision-check, so use a staging grid at 400m
        # altitude (well above any stock-town structure), staggered so
        # same-request spawns never overlap each other.
        self._spawn_counter += 1
        n = self._spawn_counter
        stage_tf = self._carla.Transform(
            self._carla.Location(
                x=float((n % 40) * 15.0),
                y=-float(((n // 40) % 40) * 15.0),
                z=400.0,
            ),
            transform.rotation,
        )
        actor = None
        for attempt in range(4):
            actor = self._world.try_spawn_actor(blueprint, stage_tf)
            if actor is not None:
                break
            stage_tf.location.z += 75.0
            stage_tf.location.x += 7.5
        if actor is None:
            # Explicit failure, never a silent drop (docs/CONTRACT.md).
            raise RuntimeError(
                f"Could not spawn actor for track_id={track_id} "
                f"(blueprint={blueprint_id}) even in the staging zone; "
                "CARLA world may be in a bad state."
            )
        actor.set_simulate_physics(False)
        offset = (0.0, 0.0, 0.0)
        try:
            bbox = actor.bounding_box
            offset = (bbox.location.x, bbox.location.y, bbox.location.z)
        except (AttributeError, RuntimeError):
            pass  # props may have no bounding_box; pivot == center is fine
        managed = ManagedActor(track_id, actor, blueprint_id, decision, offset)
        logger.info(
            "spawned track_id=%s blueprint=%s decision=%s bbox_offset=%s",
            track_id, blueprint_id, decision, offset,
        )
        return managed

    def sync(self, dynamic_objects) -> None:
        """Reconcile the CARLA world with the request's dynamic_objects."""
        requested = {}
        for obj in dynamic_objects:
            requested[obj.track_id] = frames.grpc_pose_to_tuple(obj.pose_pair.start_pose)

        for track_id in list(self._actors):
            if track_id not in requested:
                managed = self._actors.pop(track_id)
                try:
                    managed.actor.destroy()
                except RuntimeError:
                    logger.warning("destroy failed for track_id=%s", track_id)

        for track_id, pose in requested.items():
            anchored = frames.apply_anchor(
                self._scene.anchor_translation, self._scene.anchor_yaw_deg, pose
            )
            location, rotator = frames.carla_transform_tuple(*anchored, axes="flu")
            managed = self._actors.get(track_id)
            rotation = self._carla.Rotation(
                pitch=rotator[0], yaw=rotator[1], roll=rotator[2]
            )
            if managed is None:
                seed_tf = self._carla.Transform(
                    self._carla.Location(*location), rotation
                )
                managed = self._spawn(track_id, seed_tf)
                self._actors[track_id] = managed
            adjusted = frames.actor_location_for_bbox_center(
                location, rotator, managed.bbox_offset_ue
            )
            managed.actor.set_transform(
                self._carla.Transform(self._carla.Location(*adjusted), rotation)
            )

    def clear(self) -> None:
        for managed in self._actors.values():
            try:
                managed.actor.destroy()
            except RuntimeError:
                pass
        self._actors.clear()
