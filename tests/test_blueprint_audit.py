"""Gate G2's fallback audit: which actors would render as boxes.

Pure (gate G1). A run in which a vehicle, pedestrian or two-wheeler degraded
to the terminal prop shows the driver a box, so its policy score is
meaningless. The audit runs before the rollout, and the same counts land in
the run record so a pass with two boxed cyclists is visible in the evidence
rather than discovered in the video.
"""

import pytest

from alpasim_carla.catalog import BlueprintUnavailable, parse_catalog
from alpasim_carla.registry import GATED_LABELS, audit_scene_blueprints
from alpasim_carla.scenes import ActorDef, SceneManifest

CATALOG_010 = parse_catalog(
    "\n".join(
        [
            "vehicle.lincoln.mkz\tvehicle\t4.90\t2.13\t1.51",
            "walker.pedestrian.0001\twalker\t0\t0\t0",
            "static.prop.box03\tprop\t0\t0\t0",
        ]
    ),
    source="catalog_010",
)

CATALOG_WITH_TWO_WHEELERS = parse_catalog(
    "\n".join(
        [
            "vehicle.lincoln.mkz\tvehicle\t4.90\t2.13\t1.51",
            "vehicle.diamondback.century\ttwo_wheeler\t1.66\t0.42\t1.04",
            "walker.pedestrian.0001\twalker\t0\t0\t0",
            "static.prop.box03\tprop\t0\t0\t0",
        ]
    ),
    source="catalog_0916",
)


def scene_with(*actors: ActorDef) -> SceneManifest:
    return SceneManifest(
        scene_id="s",
        carla_map="Town10HD_Opt",
        actors={a.actor_id: a for a in actors},
    )


def test_gated_labels_cover_cyclists_and_motorcycles():
    assert {"cyclist", "motorcycle", "bicycle"} <= GATED_LABELS
    assert {"car", "truck", "pedestrian"} <= GATED_LABELS


def test_a_scene_that_resolves_cleanly_audits_empty():
    scene = scene_with(
        ActorDef("1", "car", (4.9, 2.1, 1.5)),
        ActorDef("2", "pedestrian", (0.8, 0.8, 1.8)),
    )
    assert audit_scene_blueprints(scene, CATALOG_010) == {}


def test_a_cyclist_on_010_is_reported_because_the_category_is_gone():
    scene = scene_with(ActorDef("7", "cyclist", (1.7, 0.5, 1.1)))
    assert audit_scene_blueprints(scene, CATALOG_010) == {"7": "cyclist"}


def test_a_motorcycle_is_reported_too():
    scene = scene_with(ActorDef("7", "motorcycle", (2.2, 0.8, 1.2)))
    assert audit_scene_blueprints(scene, CATALOG_010) == {"7": "motorcycle"}


def test_an_unlabelled_actor_is_not_gated_even_when_it_degrades():
    """Only labels we can hold the scene to; an unlabelled tiny object
    legitimately becomes a prop."""
    scene = scene_with(ActorDef("7", "", (0.3, 0.3, 0.3)))
    assert audit_scene_blueprints(scene, CATALOG_010) == {}


def test_a_vehicle_whose_override_is_missing_is_reported():
    scene = scene_with(ActorDef("7", "car", (4.9, 2.1, 1.5)))
    scene.blueprint_overrides["car"] = "vehicle.tesla.model3"
    assert audit_scene_blueprints(scene, CATALOG_010) == {"7": "car"}


def test_several_degraded_actors_are_all_reported():
    scene = scene_with(
        ActorDef("1", "cyclist", (1.7, 0.5, 1.1)),
        ActorDef("2", "car", (4.9, 2.1, 1.5)),
        ActorDef("3", "bicycle", (1.6, 0.4, 1.0)),
    )
    assert audit_scene_blueprints(scene, CATALOG_010) == {
        "1": "cyclist",
        "3": "bicycle",
    }


def test_a_catalog_that_lists_two_wheelers_audits_a_cyclist_clean():
    """The category is the difference, not the CARLA version: a listing
    that has a two-wheeler places the cyclist on it. 0.9.16 did; 0.10
    removed the category outright."""
    scene = scene_with(ActorDef("7", "cyclist", (1.7, 0.5, 1.1)))
    assert audit_scene_blueprints(scene, CATALOG_WITH_TWO_WHEELERS) == {}


def test_an_audit_with_no_catalog_refuses_rather_than_assuming_one():
    """There is no default catalogue: assuming one audited the run against
    blueprints the server does not have."""
    scene = scene_with(ActorDef("7", "cyclist", (1.7, 0.5, 1.1)))
    with pytest.raises(BlueprintUnavailable, match="list_blueprints.py"):
        audit_scene_blueprints(scene)
