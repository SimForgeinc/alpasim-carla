"""The generator's side of the terminal fallback: choose, then verify.

Pure (gate G1) - no CARLA. The ladder no longer carries a terminal fallback
constant; tools/list_blueprints.py picks one per server and records it in the
listing, and these pin the two halves of "after it has verified the prop
exists on that server".
"""

import importlib.util
from pathlib import Path

from alpasim_carla.catalog import parse_catalog

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "list_blueprints", REPO / "tools" / "list_blueprints.py"
)
list_blueprints = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(list_blueprints)  # imports carla lazily, inside main()

# As observed on the Belmont image: static.prop.box* returns zero blueprints.
BELMONT_PROPS = [
    "static.prop.advertisement",
    "static.prop.streetbarrier",
    "static.prop.trafficcone01",
]
PROPS_0916 = ["static.prop.advertisement", "static.prop.box03"]


class FakeLibrary:
    def __init__(self, ids):
        self._ids = set(ids)

    def find(self, blueprint_id):
        if blueprint_id not in self._ids:
            raise IndexError(blueprint_id)  # what CARLA raises
        return object()


def test_0916_records_box03_because_that_server_has_it():
    assert list_blueprints.choose_fallback(PROPS_0916) == "static.prop.box03"


def test_010_records_the_first_prop_in_id_order_because_there_is_no_box():
    """Belmont, measured: the tool printed fallback=static.prop.advertisement
    and that is now a recorded field rather than the tool's private choice."""
    assert (
        list_blueprints.choose_fallback(BELMONT_PROPS)
        == "static.prop.advertisement"
    )


def test_a_server_with_no_props_records_nothing():
    """Better an absent field - which the reader refuses by name - than a
    field naming a blueprint nothing verified."""
    assert list_blueprints.choose_fallback([]) == ""


def test_verification_asks_the_server_not_our_own_list():
    library = FakeLibrary(BELMONT_PROPS)
    assert list_blueprints.verify_on_server(library, "static.prop.advertisement")


def test_verification_fails_closed_when_the_server_does_not_have_the_id():
    library = FakeLibrary(BELMONT_PROPS)
    assert not list_blueprints.verify_on_server(library, "static.prop.box03")


def test_the_recorded_field_is_the_one_the_ladder_reads():
    """End to end across the seam: what the generator writes is what
    parse_catalog resolves the terminal fallback to."""
    chosen = list_blueprints.choose_fallback(BELMONT_PROPS)
    listing = "\n".join(
        [f"# fallback_blueprint: {chosen}", "vehicle.a\tvehicle\t4.9\t2.1\t1.5",
         "walker.pedestrian.0001\twalker"]
        + [f"{prop}\tprop" for prop in BELMONT_PROPS]
    )
    assert parse_catalog(listing).fallback_prop == "static.prop.advertisement"
