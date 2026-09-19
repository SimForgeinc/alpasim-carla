"""A dimension is measured or refused; it is never zero. (ADR-BRIDGE-002)

Pure (gate G1) - no CARLA. The whole seam is here rather than split between
tests/test_catalog.py and a generator file, because the defect lived in the
JOIN: `measure()` returned (0,0,0) for a spawn that never happened, the
writer formatted it as `0.00`, and the reader accepted it as a measurement.
Each half looked reasonable alone.

What this cannot cover: whether a staged spawn actually succeeds for every
vehicle blueprint on the live 0.10 Belmont server, and whether a freshly
spawned actor there reports real extents. Those need the server. What is
covered is the property that makes getting them wrong survivable - a
blueprint that does not measure cannot reach the ladder wearing a number.
"""

import importlib.util
from pathlib import Path

import pytest

from alpasim_carla.catalog import (
    MEASURED_CATEGORIES,
    UNMEASURED,
    BlueprintUnavailable,
    parse_catalog,
)

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "list_blueprints", REPO / "tools" / "list_blueprints.py"
)
list_blueprints = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(list_blueprints)  # imports carla lazily, inside main()


# -- fakes standing in for the CARLA client -----------------------------------


class FakeVector:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class FakeLocation(FakeVector):
    pass


class FakeBoundingBox:
    def __init__(self, extent):
        self.extent = extent


class FakeTransform:
    def __init__(self, location, rotation=None):
        self.location = location
        self.rotation = rotation


class FakeCarla:
    """Just the three constructors `measure` touches."""

    Location = FakeLocation
    Transform = FakeTransform


class FakeActor:
    def __init__(self, half_extent, world, key):
        self.bounding_box = FakeBoundingBox(FakeVector(*half_extent))
        self.is_alive = True
        self._world = world
        self._key = key
        self.physics = True

    def set_simulate_physics(self, enabled):
        self.physics = enabled

    def destroy(self):
        self.is_alive = False
        # Deliberately does NOT free the spawn point: that is what the
        # Belmont server did, and the reason the old loop measured one
        # vehicle and zeroed the other 144.


class FakeWorld:
    """A world whose spawn points are occupied forever once used.

    The pessimistic version of the server's behaviour on 0.10: `destroy()`
    is issued, the client believes it, and the point stays taken. A tool
    that reuses one point measures exactly one blueprint here.
    """

    def __init__(self, extents, synchronous=False, free_points=True):
        self._extents = extents  # blueprint id -> half extent
        self._taken = set()
        self._free_points = free_points
        self.synchronous = synchronous
        self.ticks = 0

    def try_spawn_actor(self, blueprint, transform):
        key = (
            round(transform.location.x, 2),
            round(transform.location.y, 2),
            round(transform.location.z, 2),
        )
        if key in self._taken:
            return None
        self._taken.add(key)
        actor = FakeActor(self._extents[blueprint.id], self, key)
        if self._free_points:
            self._taken.discard(key)
        return actor

    def get_settings(self):
        return type("Settings", (), {"synchronous_mode": self.synchronous})()

    def wait_for_tick(self):
        self.ticks += 1


class FakeBlueprint:
    def __init__(self, blueprint_id):
        self.id = blueprint_id


CARLA = FakeCarla()


# -- the measurement ----------------------------------------------------------


def test_every_vehicle_is_measured_even_when_no_spawn_point_is_ever_freed():
    """The defect, reproduced and then not reproduced.

    One fixed spawn point plus a server that does not reap gives one
    measurement and N-1 failures. A slot per blueprint gives N measurements
    with the same server.
    """
    ids = [f"vehicle.v{n}" for n in range(12)]
    world = FakeWorld({i: (2.0, 1.0, 0.75) for i in ids}, free_points=False)
    measured = [
        list_blueprints.measure(world, CARLA, FakeBlueprint(i), slot)
        for slot, i in enumerate(ids)
    ]
    assert all(dims == (4.0, 2.0, 1.5) for dims in measured)


def test_reusing_one_slot_runs_out_of_ladder_and_says_so():
    """Pinned so the fix cannot be undone by "simplifying" the slot away.

    The retry ladder alone is not the fix: on a server that never frees a
    point, four blueprints get measured and the rest do not. What makes that
    survivable is that the rest are ``None``. The old code returned
    ``(0.0, 0.0, 0.0)`` here and the file said ``0.00``.
    """
    ids = [f"vehicle.v{n}" for n in range(12)]
    world = FakeWorld({i: (2.0, 1.0, 0.75) for i in ids}, free_points=False)
    measured = [
        list_blueprints.measure(world, CARLA, FakeBlueprint(i), 0) for i in ids
    ]
    assert measured[:4] == [(4.0, 2.0, 1.5)] * 4  # the four rungs of the ladder
    assert measured[4:] == [None] * 8


def test_the_retry_ladder_climbs_when_the_first_point_is_taken():
    """The registry retries four times with an altitude bump; so does this.

    Belt to the slot's braces: the slot is what should keep the points
    distinct, and the ladder is what covers the case where something is
    sitting where the arithmetic said nothing would be.
    """
    world = FakeWorld({"vehicle.a": (2.0, 1.0, 0.75)}, free_points=False)
    assert list_blueprints.measure(world, CARLA, FakeBlueprint("vehicle.a"), 3)
    assert list_blueprints.measure(world, CARLA, FakeBlueprint("vehicle.a"), 3)


def test_a_blueprint_that_cannot_be_spawned_at_all_is_none_not_zero():
    world = FakeWorld({"vehicle.a": (2.0, 1.0, 0.75)}, free_points=False)
    blueprint = FakeBlueprint("vehicle.a")
    for _ in range(4):  # exhaust the ladder for this slot
        list_blueprints.measure(world, CARLA, blueprint, 0)
    assert list_blueprints.measure(world, CARLA, blueprint, 0) is None


def test_a_dead_actor_is_unmeasured_rather_than_a_zeroed_box():
    """"Read the extents while the actor is alive" as a check, not a comment.

    The recorded hypothesis for Belmont was that the box was read after the
    actor was gone. It was not - but a handle that dies under the read is
    still the failure mode that must not produce a number.
    """

    class DeadOnArrival(FakeWorld):
        def try_spawn_actor(self, blueprint, transform):
            actor = super().try_spawn_actor(blueprint, transform)
            actor.is_alive = False
            return actor

    world = DeadOnArrival({"vehicle.a": (2.0, 1.0, 0.75)})
    assert list_blueprints.measure(world, CARLA, FakeBlueprint("vehicle.a")) is None


def test_a_live_actor_reporting_a_zeroed_box_is_unmeasured():
    world = FakeWorld({"vehicle.a": (0.0, 0.0, 0.0)})
    assert list_blueprints.measure(world, CARLA, FakeBlueprint("vehicle.a")) is None


def test_the_box_is_read_after_a_tick_when_the_world_is_asynchronous():
    world = FakeWorld({"vehicle.a": (2.0, 1.0, 0.75)})
    list_blueprints.measure(world, CARLA, FakeBlueprint("vehicle.a"))
    assert world.ticks == 1


def test_a_synchronous_world_is_not_waited_on():
    """Nobody here owns the tick in synchronous mode; waiting would hang."""
    world = FakeWorld({"vehicle.a": (2.0, 1.0, 0.75)}, synchronous=True)
    assert list_blueprints.measure(world, CARLA, FakeBlueprint("vehicle.a"))
    assert world.ticks == 0


def test_physics_is_disabled_so_the_actor_does_not_fall_into_the_next_slot():
    """A vehicle spawned at 400 m with physics on is falling by the time the
    next blueprint wants a point near it. The registry disables physics for
    the same reason."""
    spawned = []

    class Watching(FakeWorld):
        def try_spawn_actor(self, blueprint, transform):
            actor = super().try_spawn_actor(blueprint, transform)
            spawned.append(actor)
            return actor

    world = Watching({"vehicle.a": (2.0, 1.0, 0.75)})
    list_blueprints.measure(world, CARLA, FakeBlueprint("vehicle.a"))
    assert spawned and spawned[0].physics is False


def test_each_slot_is_a_distinct_spawn_point():
    points = {
        (
            list_blueprints.staging_transform(CARLA, slot).location.x,
            list_blueprints.staging_transform(CARLA, slot).location.y,
        )
        for slot in range(200)
    }
    assert len(points) == 200


# -- the writer ---------------------------------------------------------------


def test_the_two_spellings_of_the_token_agree():
    """The tool cannot import the package on the box it runs on, so the
    constant is spelled twice. This is the seam that keeps them one word."""
    assert list_blueprints.UNMEASURED == UNMEASURED
    assert list_blueprints.MEASURED_CATEGORIES == MEASURED_CATEGORIES


def test_an_unmeasured_vehicle_is_written_as_the_token():
    row = list_blueprints.format_row("vehicle.a", "vehicle", None)
    assert row == f"vehicle.a\tvehicle\t{UNMEASURED}"


def test_no_row_this_writer_produces_carries_a_zero_dimension():
    """The invariant, stated as one assertion: there is no 0.00 in the file.

    Sub-centimetre extents round to 0.00 in the format, so the guard is on
    the formatted string. A vehicle 4 mm long is not a measurement either.
    """
    candidates = [
        None,
        (0.0, 0.0, 0.0),
        (0.004, 1.9, 1.5),
        (4.9, 0.004, 1.5),
        (4.9, 2.1, 0.0),  # height is unused by the ladder, but still not 0.00
    ]
    rows = [
        list_blueprints.format_row("vehicle.a", category, dims)
        for dims in candidates
        for category in MEASURED_CATEGORIES
    ]
    assert all("0.00" not in row for row in rows)
    assert all(row.endswith(UNMEASURED) for row in rows)


def test_a_real_measurement_is_written_to_two_decimals():
    row = list_blueprints.format_row("vehicle.a", "vehicle", (6.36, 2.35, 2.43))
    assert row == "vehicle.a\tvehicle\t6.36\t2.35\t2.43"


def test_walker_and_prop_rows_carry_no_numbers_at_all():
    """They used to be written `0.00 0.00 0.00` - a column of zeros meaning
    "not applicable" beside a column of zeros meaning "the measurement
    failed". Dropping them is what lets the invariant above have no
    exceptions in it."""
    for category in ("walker", "prop"):
        row = list_blueprints.format_row("x.y", category, (1.0, 2.0, 3.0))
        assert row == f"x.y\t{category}"


# -- the reader ---------------------------------------------------------------


MEASURED_LISTING = """\
# fallback_blueprint: static.prop.advertisement
vehicle.ambulance.ford\tvehicle\t6.36\t2.35\t2.43
vehicle.trailer.x\tvehicle\t8.39\t2.82\t3.10
walker.pedestrian.0001\twalker
static.prop.advertisement\tprop
"""


def test_a_listing_of_real_measurements_still_loads():
    catalog = parse_catalog(MEASURED_LISTING)
    assert len(catalog.vehicles) == 2


def test_the_belmont_listing_as_it_was_generated_is_now_refused():
    """The file that cost the campaign, in miniature: one measured row and
    the rest zeros. It parses as valid floats, which is precisely why the
    reader has to refuse it rather than warn."""
    poisoned = MEASURED_LISTING.replace(
        "vehicle.trailer.x\tvehicle\t8.39\t2.82\t3.10",
        "vehicle.trailer.x\tvehicle\t0.00\t0.00\t0.00",
    )
    with pytest.raises(BlueprintUnavailable) as exc:
        parse_catalog(poisoned, source="blueprints_0.10.txt")
    message = str(exc.value)
    assert "vehicle.trailer.x" in message
    assert "blueprints_0.10.txt" in message
    assert "tools/list_blueprints.py" in message


def test_the_token_the_writer_emits_is_refused_by_the_reader():
    """The seam, end to end: what the generator writes for a blueprint it
    could not measure is what the loader refuses by name."""
    row = list_blueprints.format_row("vehicle.trailer.x", "vehicle", None)
    listing = MEASURED_LISTING.replace(
        "vehicle.trailer.x\tvehicle\t8.39\t2.82\t3.10", row
    )
    with pytest.raises(BlueprintUnavailable, match="vehicle.trailer.x"):
        parse_catalog(listing)


def test_the_refusal_counts_the_rows_rather_than_naming_all_144():
    listing = "# fallback_blueprint: static.prop.advertisement\n"
    listing += "".join(
        f"vehicle.v{n}\tvehicle\t0.00\t0.00\t0.00\n" for n in range(144)
    )
    listing += "vehicle.ambulance.ford\tvehicle\t6.36\t2.35\t2.43\n"
    listing += "walker.pedestrian.0001\twalker\nstatic.prop.advertisement\tprop\n"
    message = str(pytest.raises(BlueprintUnavailable, parse_catalog, listing).value)
    assert "144" in message
    assert "141 more" in message


def test_a_zero_two_wheeler_is_refused_too():
    listing = MEASURED_LISTING + "vehicle.bike.a\ttwo_wheeler\t0.00\t0.00\t0.00\n"
    with pytest.raises(BlueprintUnavailable, match="vehicle.bike.a"):
        parse_catalog(listing)


def test_an_all_zero_listing_says_the_measurement_failed_not_that_rows_are_missing():
    """A listing whose vehicles are all zeros has no vehicle candidates
    either. "lists no vehicle blueprint" would send the reader looking for a
    missing row rather than at the measurement."""
    listing = MEASURED_LISTING.replace("6.36\t2.35\t2.43", "0.00\t0.00\t0.00")
    listing = listing.replace("8.39\t2.82\t3.10", "0.00\t0.00\t0.00")
    with pytest.raises(BlueprintUnavailable) as exc:
        parse_catalog(listing)
    assert "no measurement" in str(exc.value)


def test_zeros_on_walker_and_prop_rows_are_still_tolerated():
    """Older listings wrote them, and nothing reads them. The refusal is
    scoped to the rows whose numbers decide which vehicle a scene gets."""
    listing = MEASURED_LISTING.replace(
        "walker.pedestrian.0001\twalker", "walker.pedestrian.0001\twalker\t0.0\t0.0\t0.0"
    ).replace(
        "static.prop.advertisement\tprop",
        "static.prop.advertisement\tprop\t0.0\t0.0\t0.0",
    )
    assert parse_catalog(listing).walker == "walker.pedestrian.0001"


def test_a_vehicle_row_with_no_dimension_columns_at_all_is_a_parse_error():
    """Not a silent pass: the row shape is wrong, and the message says both
    shapes that are right."""
    listing = MEASURED_LISTING + "vehicle.z\tvehicle\n"
    with pytest.raises(ValueError, match=UNMEASURED):
        parse_catalog(listing)


def test_the_refusal_explains_what_a_zero_does_rather_than_only_that_it_is_wrong():
    """Whoever hits this must not have to read the diagnosis to know why a
    zero is refused instead of tolerated with a warning."""
    poisoned = MEASURED_LISTING.replace("8.39\t2.82\t3.10", "0.00\t0.00\t0.00")
    message = str(pytest.raises(BlueprintUnavailable, parse_catalog, poisoned).value)
    assert "nearest" in message
    assert "ambulance" in message
