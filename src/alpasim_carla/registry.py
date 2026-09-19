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
from alpasim_carla.catalog import (
    BlueprintCatalog,
    BlueprintUnavailable,
    default_catalog,
)
from alpasim_carla.scenes import ActorDef, SceneManifest, TrafficContradiction

logger = logging.getLogger("alpasim_carla.registry")

# Blueprint candidates and their dimensions now live in alpasim_carla.catalog,
# loaded from a per-server listing (tools/list_blueprints.py). The curated
# CARLA 0.9.16 table remains there as catalog.default_catalog().

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


@dataclass
class BlueprintChoice:
    """What the ladder picked, and whether it had to give up to pick it.

    ``is_fallback`` is the machine-readable signal Gate G2 checks: a run in
    which any vehicle or pedestrian resolved to the terminal prop rendered
    boxes to the driver, so its policy score means nothing.
    """

    blueprint_id: str
    decision: str
    is_fallback: bool = False


def choose_blueprint(
    track_id: str,
    actor_def: Optional[ActorDef],
    scene: SceneManifest,
    catalog: Optional[BlueprintCatalog] = None,
) -> BlueprintChoice:
    """Pick a blueprint for one tracked object. Never raises, never skips.

    Ladder: manifest ``blueprint_overrides[label]`` -> category table by label
    -> dims heuristic -> the catalogue's terminal prop. Every rung is
    validated against ``catalog`` membership, so an id that this server does
    not have degrades here rather than raising inside ``_spawn``.
    """
    catalog = catalog or default_catalog()
    label = (actor_def.label if actor_def else "").strip().lower()
    size = actor_def.size_lwh if actor_def else (4.5, 1.9, 1.6)
    length, width, height = size

    def degrade(reason: str, wanted: str = "") -> BlueprintChoice:
        logger.warning(
            "blueprint_fallback track_id=%s label=%r dims=%.2fx%.2fx%.2f "
            "wanted=%s -> %s (%s; object NOT dropped)",
            track_id, label, length, width, height,
            wanted or "-", catalog.fallback_prop, reason,
        )
        tag = f"{reason}[{label or 'no-label'}]"
        if wanted:
            tag += f"+missing:{wanted}"
        return BlueprintChoice(catalog.fallback_prop, tag, is_fallback=True)

    def take(blueprint_id: str, decision: str) -> BlueprintChoice:
        if not catalog.has(blueprint_id):
            return degrade("missing_blueprint", wanted=blueprint_id)
        return BlueprintChoice(blueprint_id, decision)

    if label and label in scene.blueprint_overrides:
        return take(scene.blueprint_overrides[label], f"override[{label}]")
    if label in _VEHICLE_LABELS:
        if not catalog.vehicles:
            return degrade("no_vehicle_in_catalog")
        return take(_nearest_by_dims(catalog.vehicles, size), f"vehicle[{label}]")
    if label in _TWO_WHEELER_LABELS:
        # CARLA 0.10 removed the motorcycle and bicycle categories outright.
        if not catalog.two_wheelers:
            return degrade("no_two_wheeler_in_catalog")
        return take(
            _nearest_by_dims(catalog.two_wheelers, size), f"two_wheeler[{label}]"
        )
    if label in _WALKER_LABELS:
        return take(catalog.walker, f"walker[{label}]")

    # Unknown / missing label: dims heuristic, then the terminal prop.
    if 2.5 < length < 13.0 and 1.3 < width < 3.2 and catalog.vehicles:
        blueprint = _nearest_by_dims(catalog.vehicles, size)
        logger.warning(
            "blueprint_heuristic track_id=%s label=%r dims=%.2fx%.2fx%.2f -> %s "
            "(car-like dims heuristic; add the label to the scene manifest "
            "blueprint_overrides to silence)",
            track_id, label, length, width, height, blueprint,
        )
        return take(blueprint, f"dims_heuristic[{label or 'no-label'}]")
    if length < 1.2 and height > 1.2:
        logger.warning(
            "blueprint_heuristic track_id=%s label=%r dims=%.2fx%.2fx%.2f -> %s "
            "(person-like dims heuristic)",
            track_id, label, length, width, height, catalog.walker,
        )
        return take(catalog.walker, f"dims_heuristic_walker[{label or 'no-label'}]")
    return degrade("box_fallback")


# Labels the scene is held to. An actor carrying one of these must resolve to
# a real blueprint: a boxed car, pedestrian or cyclist is visible to the
# driver and invalidates the run's policy score. Unlabelled actors are not
# gated - a tiny unlabelled object legitimately becomes a prop.
GATED_LABELS = _VEHICLE_LABELS | _TWO_WHEELER_LABELS | _WALKER_LABELS


def audit_scene_blueprints(
    scene: SceneManifest, catalog: Optional[BlueprintCatalog] = None
) -> Dict[str, str]:
    """Return ``{track_id: label}`` for gated actors that would render as props.

    Pure: resolves every actor in the manifest through the same ladder the
    registry uses, without touching CARLA. Gate G2 runs this before a rollout
    and records the result, so a run that passed with two boxed cyclists is
    visible in the evidence instead of being found in the video.
    """
    catalog = catalog or default_catalog()
    degraded: Dict[str, str] = {}
    for track_id, actor_def in scene.actors.items():
        label = (actor_def.label or "").strip().lower()
        if label not in GATED_LABELS:
            continue
        if choose_blueprint(track_id, actor_def, scene, catalog).is_fallback:
            degraded[track_id] = label
    return degraded


@dataclass
class ManagedActor:
    track_id: str
    actor: object  # carla.Actor
    blueprint_id: str
    decision: str
    bbox_offset_ue: Tuple[float, float, float]
    is_fallback: bool = False
    label: str = ""


class ActorRegistry:
    def __init__(
        self,
        carla_module,
        world,
        scene: SceneManifest,
        catalog: Optional[BlueprintCatalog] = None,
    ):
        self._carla = carla_module
        self._world = world
        self._scene = scene
        self._catalog = catalog or default_catalog()
        self._actors: Dict[str, ManagedActor] = {}
        self._blueprints = world.get_blueprint_library()
        self._spawn_counter = 0

    @property
    def actor_count(self) -> int:
        return len(self._actors)

    @property
    def fallback_actors(self) -> Dict[str, str]:
        """``{track_id: label}`` for actors that spawned as the terminal
        prop. Recorded per run so a pass with boxed actors is visible in
        the evidence rather than found later in the video."""
        return {
            track_id: managed.label
            for track_id, managed in self._actors.items()
            if managed.is_fallback
        }

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
        choice = choose_blueprint(track_id, actor_def, self._scene, self._catalog)
        blueprint_id, decision = choice.blueprint_id, choice.decision
        try:
            blueprint = self._blueprints.find(blueprint_id)
        except (IndexError, RuntimeError) as exc:
            # choose_blueprint already validated membership against the
            # catalogue, so reaching here means the catalogue disagrees with
            # the live server - a stale listing file. Name it; do not let an
            # IndexError escape as an opaque gRPC INTERNAL mid-rollout.
            raise BlueprintUnavailable(
                f"blueprint {blueprint_id!r} chosen for track_id={track_id} "
                f"is absent from this CARLA server, but the catalogue "
                f"({self._catalog.source}) lists it. Regenerate the listing "
                f"with tools/list_blueprints.py against this server."
            ) from exc
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
        managed = ManagedActor(
            track_id, actor, blueprint_id, decision, offset,
            choice.is_fallback, (actor_def.label if actor_def else ""),
        )
        # Gate G2 greps this line for fallback=true.
        logger.info(
            "spawned track_id=%s blueprint=%s decision=%s fallback=%s bbox_offset=%s",
            track_id, blueprint_id, decision,
            "true" if choice.is_fallback else "false", offset,
        )
        return managed

    def sync(self, dynamic_objects) -> None:
        """Reconcile the CARLA world with the request's dynamic_objects.

        A scene declaring ``traffic: clip_replay_suppressed`` is held to it
        here. This is the only process that sees what was actually on the
        road: the run manifest's ``traffic`` field is derived from the
        experiment config, so it records the INTENT to suppress, and if the
        suppression does not take effect - patch 0004 unapplied, a config
        key that moved - both records still say ``suppressed`` while the
        clip's 62 vehicles are spawned behind them. Refusing on the first
        request costs one rollout; not refusing costs a campaign, which is
        the arithmetic the 2026-09-19 Belmont seeds settled.

        Only that direction is checked. An EMPTY request against a scene
        declaring ``clip_replay`` is not an error: actors legitimately come
        and go within a rollout, so "no actors this frame" says nothing.
        """
        if self._scene.traffic == "clip_replay_suppressed" and dynamic_objects:
            raise TrafficContradiction(
                f"scene {self._scene.scene_id!r} declares "
                f"traffic: clip_replay_suppressed, but this request carries "
                f"{len(dynamic_objects)} dynamic object(s). The suppression "
                f"did not take effect, so the run would contain the clip's "
                f"replayed traffic while every record of it - this manifest "
                f"and the run manifest, which derives its `traffic` from the "
                f"experiment config - says the road was empty. Check "
                f"SimulationConfig.replayed_traffic on the runtime side, or "
                f"correct the manifest's traffic: field to what this run "
                f"actually contains."
            )
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
