"""The blueprint fallback ladder, driven by a catalogue.

Pure (gate G1) - choose_blueprint touches no CARLA. These tests pin the
behaviour that Gate G2 greps for: every choice says whether it degraded to the
terminal prop, so a run where NPCs silently became boxes is detectable.
"""

import pytest

from alpasim_carla.catalog import parse_catalog
from alpasim_carla.registry import choose_blueprint
from alpasim_carla.scenes import ActorDef, SceneManifest

# A 0.10-shaped catalogue: no two-wheelers, ue4-prefixed survivors, renamed
# firetruck. None of the curated 0.9.16 vehicle ids appear.
CATALOG_010 = parse_catalog(
    "\n".join(
        [
            "vehicle.mini.cooper\tvehicle\t3.80\t1.92\t1.45",
            "vehicle.ue4.audi.tt\tvehicle\t4.18\t1.99\t1.39",
            "vehicle.lincoln.mkz\tvehicle\t4.90\t2.13\t1.51",
            "vehicle.firetruck.actors\tvehicle\t8.49\t2.94\t3.41",
            "walker.pedestrian.0001\twalker\t0\t0\t0",
            "static.prop.box03\tprop\t0\t0\t0",
        ]
    ),
    source="catalog_010",
)


def scene(**overrides) -> SceneManifest:
    return SceneManifest(
        scene_id="s", carla_map="Town10HD_Opt", blueprint_overrides=overrides
    )


def test_manifest_override_wins_when_the_catalogue_has_it():
    choice = choose_blueprint(
        "7",
        ActorDef("7", "automobile", (4.5, 1.9, 1.6)),
        scene(automobile="vehicle.lincoln.mkz"),
        CATALOG_010,
    )
    assert choice.blueprint_id == "vehicle.lincoln.mkz"
    assert not choice.is_fallback


def test_vehicle_label_picks_nearest_catalogue_entry_by_length_and_width():
    choice = choose_blueprint(
        "7", ActorDef("7", "car", (4.85, 2.10, 1.5)), scene(), CATALOG_010
    )
    assert choice.blueprint_id == "vehicle.lincoln.mkz"
    assert not choice.is_fallback


def test_walker_label_picks_the_catalogue_walker():
    choice = choose_blueprint(
        "7", ActorDef("7", "pedestrian", (0.8, 0.8, 1.8)), scene(), CATALOG_010
    )
    assert choice.blueprint_id == "walker.pedestrian.0001"
    assert not choice.is_fallback


def test_car_like_dims_without_a_label_pick_a_vehicle():
    choice = choose_blueprint("7", None, scene(), CATALOG_010)
    assert choice.blueprint_id.startswith("vehicle.")
    assert not choice.is_fallback


def test_person_like_dims_without_a_label_pick_the_walker():
    choice = choose_blueprint(
        "7", ActorDef("7", "", (0.7, 0.7, 1.8)), scene(), CATALOG_010
    )
    assert choice.blueprint_id == "walker.pedestrian.0001"


def test_unmatchable_actor_degrades_to_the_prop_and_says_so():
    choice = choose_blueprint(
        "7", ActorDef("7", "", (0.3, 0.3, 0.3)), scene(), CATALOG_010
    )
    assert choice.blueprint_id == "static.prop.box03"
    assert choice.is_fallback


def test_two_wheeler_label_degrades_to_the_prop_when_010_has_no_two_wheelers():
    """0.10 removed the motorcycle and bicycle categories. The old ladder
    called min() on an empty candidate list and raised ValueError."""
    choice = choose_blueprint(
        "7", ActorDef("7", "cyclist", (1.7, 0.5, 1.1)), scene(), CATALOG_010
    )
    assert choice.blueprint_id == "static.prop.box03"
    assert choice.is_fallback


def test_an_override_the_server_does_not_have_degrades_instead_of_being_trusted():
    """The override names a 0.9.16 id; this server has no such blueprint."""
    choice = choose_blueprint(
        "7",
        ActorDef("7", "automobile", (4.5, 1.9, 1.6)),
        scene(automobile="vehicle.tesla.model3"),
        CATALOG_010,
    )
    assert choice.blueprint_id == "static.prop.box03"
    assert choice.is_fallback
    assert "missing" in choice.decision


def test_decision_string_records_how_the_choice_was_made():
    choice = choose_blueprint(
        "7", ActorDef("7", "car", (4.85, 2.10, 1.5)), scene(), CATALOG_010
    )
    assert "vehicle[car]" in choice.decision


@pytest.mark.parametrize("label", ["automobile", "truck", "bus", "van"])
def test_every_vehicle_synonym_resolves_without_degrading(label):
    choice = choose_blueprint(
        "7", ActorDef("7", label, (4.7, 2.0, 1.5)), scene(), CATALOG_010
    )
    assert not choice.is_fallback
