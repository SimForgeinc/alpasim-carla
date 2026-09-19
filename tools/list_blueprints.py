#!/usr/bin/env python
"""Day-one check: list what this CARLA server can actually spawn.

Writes the blueprint listing that alpasim_carla.catalog reads, so the fallback
ladder is filled in from the server in front of us rather than from a curated
CARLA 0.9.16 table. On 0.10 that table is wrong in every row: none of the
eight vehicle ids exist verbatim, both two-wheeler categories were removed,
and several survivors carry a ``vehicle.ue4.<make>.<model>`` id.

Dimensions are not available from a blueprint - only a spawned actor has a
bounding box - so each vehicle is spawned at altitude, measured while it is
alive, and destroyed. Walkers and props are listed without dimensions; the
ladder does not use dims for them.

A vehicle this tool cannot measure is written as ``unmeasured``, never as
``0.00``, and a listing containing one is refused by ``catalog.py`` at load.
That is the whole point of :func:`measure` returning ``None``: the previous
version returned ``(0.0, 0.0, 0.0)`` for a spawn that never happened, which
is a lie in the shape of a measurement, and it cost the Belmont Gate C
campaign of 2026-09-19 - 462 NPC spawn decisions, every one of them
``vehicle.ambulance.ford``. See
docs/adr/ADR-BRIDGE-002-a-dimension-is-measured-or-refused.md.

This tool also decides, and RECORDS, the terminal fallback: the blueprint an
actor the ladder cannot otherwise place degrades to. It is written into the
listing as a ``# fallback_blueprint: <id>`` field, after the id has been
verified to exist on this server, because it is a per-image fact and not a
code default - ``static.prop.box03`` is the terminal on 0.9.16 and does not
exist at all on the 0.10 Belmont image, where the terminal is
``static.prop.advertisement``. See
docs/adr/ADR-BRIDGE-001-terminal-fallback-is-a-recorded-fact.md.

Usage:

    python tools/list_blueprints.py --carla-port 3000 \\
        --out blueprints_0.10.txt

Then serve with:

    alpasim-carla serve --blueprint-catalog blueprints_0.10.txt ...

The script also answers the other day-one questions in one pass and prints
them to stderr: the server version string, the map name before and after a
load (the exact strings the manifest compare depends on), whether
``load_world_if_different`` exists on this client, whether any
``sensor.other.v2x*`` blueprint is present, whether a ``static.prop.box*``
exists to serve as the ladder's terminal fallback, whether set_weather
raises or is tolerated, and whether a rigidly-attached camera follows its
parent vehicle under synchronous mode - which is ADR-015's premise.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Tuple

Dims = Tuple[float, float, float]


#: The tool's preference when the server has it, and nothing more. It is a
#: SELECTION RULE here, not a fallback the ladder carries: whatever wins is
#: verified on the server and written into the listing as a fact about that
#: image. On 0.9.16 this id exists and is recorded; on the 0.10 Belmont
#: image `static.prop.box*` returns zero blueprints, so the first prop in
#: id order is recorded instead - which is how
#: `fallback=static.prop.advertisement` came out of this tool on Belmont.
PREFERRED_FALLBACK = "static.prop.box03"

#: What a measured column says when the measurement did not happen, and the
#: categories that have measured columns at all. Spelled here rather than
#: imported from ``alpasim_carla.catalog``: this script runs as
#: ``python tools/list_blueprints.py`` against a CARLA-flavoured interpreter
#: that may not have the package on its path, which is why ``src`` is only
#: put on ``sys.path`` at the end of :func:`main`. The two spellings are
#: pinned equal in tests/test_blueprint_dimensions.py, which is a cheaper
#: seam than an import that can fail on the box this has to run on.
UNMEASURED = "unmeasured"
MEASURED_CATEGORIES = ("vehicle", "two_wheeler")


def choose_fallback(props: List[str]) -> str:
    """Pick the terminal fallback for THIS server from its own props."""
    if not props:
        return ""
    if PREFERRED_FALLBACK in props:
        return PREFERRED_FALLBACK
    return sorted(props)[0]


def verify_on_server(library, blueprint_id: str) -> bool:
    """Ask the server for the blueprint by id, not our own list.

    The field is a claim about the server, so it is checked against the
    server: ``find()`` raises for an id the library does not have. Writing
    an unverified terminal would move the old failure - an id that is not
    there - from a constant into a file, which is no improvement.
    """
    try:
        return library.find(blueprint_id) is not None
    except (IndexError, RuntimeError):
        return False


def categorize(blueprint) -> str:
    bid = blueprint.id
    if bid.startswith("walker."):
        return "walker"
    if bid.startswith("static.prop."):
        return "prop"
    if bid.startswith("vehicle."):
        if blueprint.has_attribute("number_of_wheels"):
            try:
                if int(blueprint.get_attribute("number_of_wheels")) == 2:
                    return "two_wheeler"
            except (ValueError, RuntimeError):
                pass
        return "vehicle"
    return ""


def staging_transform(carla, slot: int):
    """A spawn point no other blueprint in this run has used.

    The same grid ``ActorRegistry._spawn`` stages on, for the same reason
    and with the numbers copied deliberately: 400 m is above any stock-town
    structure and 15 m apart is wider than the longest vehicle, so two
    consecutive blueprints cannot collide with each other.

    The registry already knew that one fixed spawn point does not work.
    This tool used ``(0, 0, 500)`` for every blueprint in the library.
    """
    return carla.Transform(
        carla.Location(
            x=float((slot % 40) * 15.0),
            y=-float(((slot // 40) % 40) * 15.0),
            z=400.0,
        )
    )


def settle(world) -> None:
    """Let the server register the actor before its bounding box is read.

    ``bounding_box`` is served out of the client-side actor snapshot, which
    is refreshed on a world tick. Reading it in the same breath as the spawn
    can return the pre-registration default, which is a zeroed box - and a
    zeroed box read off a live actor is exactly the failure this file exists
    to make impossible, so it is worth one tick to avoid.

    In synchronous mode nobody here owns the tick, so waiting would hang
    until the timeout; this tool runs against an asynchronous world (the
    only place it ticks is :func:`probe_attach`, which restores the
    setting).
    """
    try:
        if world.get_settings().synchronous_mode:
            return
        world.wait_for_tick()
    except (AttributeError, RuntimeError):
        pass


def measure(world, carla, blueprint, slot: int = 0) -> Optional[Dims]:
    """Spawn at altitude, read the box off the LIVE actor, destroy.

    Returns ``None`` - never a zero - when the blueprint could not be
    measured. ``None`` is written into the listing as ``unmeasured`` and the
    listing is then refused at load, which is the one behaviour this
    function's caller must not be able to lose.

    WHAT WENT WRONG ON BELMONT, AND WHAT IT ACTUALLY WAS

    Measured on the Belmont image, 2026-09-19: the generated listing had
    **144 of 145 rows reading 0.00**, and only ``vehicle.ambulance.ford``
    carried real extents (6.36 x 2.35 x 2.43). The run also printed

        WARNING: attempting to destroy an actor that is already dead:
                 Actor 81 (vehicle.ambulance.ford)

    The hypothesis recorded here was that the extents were read after the
    actor was gone. **They were not.** The read sat inside the ``try``,
    above the ``finally`` that destroyed - the actor was alive at every
    read. The cause the code actually supports is one line further up:
    every blueprint in the library was spawned at the SAME transform,
    ``(0, 0, 500)``, with a single attempt, and ``try_spawn_actor`` returns
    ``None`` rather than raising when that point is occupied. That ``None``
    was converted to ``(0.0, 0.0, 0.0)`` and written as a measurement.

    It fits what was observed, which the old hypothesis did not:
    ``vehicle.ambulance.ford`` sorts first among ``vehicle.*``, so it is the
    one that got the free spawn point; the "already dead" warning names it
    alone, and says its destroy did not land where the client thought it
    did, leaving the point occupied for the 144 blueprints behind it. One
    actor that spawned, one actor warned about, 144 that never spawned at
    all.

    So the fix is three things, and only the first is the spawn:

      * a staging slot per blueprint, with the registry's retry ladder, so
        an actor the server has not reaped yet cannot block its successor;
      * the box read off an actor asserted alive, after one tick;
      * and a failure that is a refusal rather than a zero, because the
        first two are a hypothesis about a server this cannot reach and the
        third is not. If the spawn fix is wrong, the listing says
        ``unmeasured`` 145 times and nothing will load it. If the old code
        was wrong, it said ``0.00`` 144 times and everything loaded it.
    """
    transform = staging_transform(carla, slot)
    actor = None
    for _ in range(4):
        actor = world.try_spawn_actor(blueprint, transform)
        if actor is not None:
            break
        transform.location.z += 75.0
        transform.location.x += 7.5
    if actor is None:
        return None

    dims: Optional[Dims] = None
    try:
        try:
            # Nothing here is driven; a falling actor is one more way for a
            # spawn point to still be occupied when the next blueprint wants
            # it. The registry disables physics for the same reason.
            actor.set_simulate_physics(False)
        except (AttributeError, RuntimeError):
            pass
        settle(world)
        if not getattr(actor, "is_alive", True):
            return None
        extent = actor.bounding_box.extent
        dims = (2 * extent.x, 2 * extent.y, 2 * extent.z)
    except (AttributeError, RuntimeError):
        return None
    finally:
        try:
            actor.destroy()
        except RuntimeError:
            pass

    if min(dims) <= 0.0:
        # A live actor reporting a flat box. Whatever that is, it is not a
        # vehicle 0 m long, and it must not reach the file as one. Height is
        # included even though the ladder ignores it: a zero anywhere in the
        # box says the read was wrong, not that the vehicle is thin.
        return None
    return dims


def format_row(blueprint_id: str, category: str, dims: Optional[Dims]) -> str:
    """One listing row, and the place a zero cannot get through.

    Only ``vehicle`` and ``two_wheeler`` rows carry numbers, because they
    are the only rows whose numbers anything reads. Walker and prop rows
    used to be written ``0.00	0.00	0.00``; dropping those columns is
    what lets the invariant be stated without an exception in it - **no
    ``0.00`` appears anywhere in a listing this function writes.**

    The zero guard is on the FORMATTED string rather than on the float,
    because 0.004 m is not a vehicle either and ``f"{0.004:.2f}"`` is
    ``0.00``. What must never appear in the file is what is checked.
    """
    if category not in MEASURED_CATEGORIES:
        return f"{blueprint_id}\t{category}"
    if dims is None:
        return f"{blueprint_id}\t{category}\t{UNMEASURED}"
    formatted = [f"{value:.2f}" for value in dims]
    if "0.00" in formatted:
        return f"{blueprint_id}\t{category}\t{UNMEASURED}"
    return f"{blueprint_id}\t{category}\t" + "\t".join(formatted)


def probe_attach(world, carla, say) -> None:
    """Settle ADR-015's premise: does a rigidly-attached camera follow the
    vehicle under synchronous mode on THIS build?

    CARLA 0.10.0's own first-steps documentation shows
    ``world.spawn_actor(camera_bp, transform, attach_to=vehicle)`` for
    ``sensor.camera.rgb``, so the API exists in the release. What is
    unverified is whether it behaves correctly under synchronous mode on
    the Belmont build, and whether Rigid is the default attachment type.

    Spawn a vehicle, attach a camera, tick, teleport the vehicle, tick,
    and check the camera moved with it. If it did not, ADR-015's approach
    does not work and the ego-camera design needs rethinking before any
    code is written against it.
    """
    library = world.get_blueprint_library()
    vehicles = library.filter("vehicle.*")
    if not vehicles:
        say("attach_to probe          : SKIPPED, no vehicle blueprints")
        return

    settings = world.get_settings()
    was_sync = settings.synchronous_mode
    was_delta = settings.fixed_delta_seconds
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.1
    world.apply_settings(settings)

    vehicle = camera = None
    try:
        start = carla.Transform(carla.Location(x=0.0, y=0.0, z=300.0))
        vehicle = world.try_spawn_actor(vehicles[0], start)
        if vehicle is None:
            say("attach_to probe          : SKIPPED, could not spawn a vehicle")
            return

        camera_bp = library.find("sensor.camera.rgb")
        camera_bp.set_attribute("image_size_x", "64")
        camera_bp.set_attribute("image_size_y", "64")
        offset = carla.Transform(carla.Location(x=2.0, y=0.0, z=1.5))
        try:
            camera = world.spawn_actor(
                camera_bp, offset, attach_to=vehicle,
                attachment_type=carla.AttachmentType.Rigid,
            )
            how = "explicit AttachmentType.Rigid"
        except (AttributeError, TypeError, RuntimeError) as exc:
            say(f"attach_to probe          : Rigid not accepted ({exc}); "
                f"retrying with the default")
            camera = world.spawn_actor(camera_bp, offset, attach_to=vehicle)
            how = "default attachment type"

        world.tick()
        before = camera.get_transform().location

        moved_to = carla.Transform(carla.Location(x=120.0, y=45.0, z=300.0))
        vehicle.set_transform(moved_to)
        world.tick()
        after = camera.get_transform().location

        delta = ((after.x - before.x) ** 2 + (after.y - before.y) ** 2) ** 0.5
        followed = delta > 1.0
        say(f"attach_to probe          : {how}")
        say(f"  camera before          : ({before.x:.2f}, {before.y:.2f}, {before.z:.2f})")
        say(f"  camera after           : ({after.x:.2f}, {after.y:.2f}, {after.z:.2f})")
        say(f"  moved with vehicle     : {followed}  (delta {delta:.2f} m)")
        if not followed:
            say("  *** ADR-015 PREMISE FAILS: the attached camera did not "
                "follow the vehicle. The ego-camera design needs rethinking.")
    finally:
        for actor in (camera, vehicle):
            if actor is not None:
                try:
                    actor.destroy()
                except RuntimeError:
                    pass
        settings.synchronous_mode = was_sync
        settings.fixed_delta_seconds = was_delta
        world.apply_settings(settings)


def probe(client, world, carla, map_name: str) -> None:
    """Print the day-one facts that no CARLA document settles."""
    say = lambda *a: print(*a, file=sys.stderr)  # noqa: E731
    say("=== day-one probe ===")
    say(f"server_version           : {client.get_server_version()!r}")
    say(f"client_version           : {client.get_client_version()!r}")
    say(f"map_name_before_load     : {world.get_map().name!r}")
    say(
        "has_load_world_if_different: "
        f"{hasattr(client, 'load_world_if_different')}"
    )

    library = world.get_blueprint_library()
    v2x = [b.id for b in library.filter("sensor.other.v2x*")]
    say(f"v2x_blueprints           : {v2x or 'NONE'}")
    props = [b.id for b in library.filter("static.prop.box*")]
    say(
        "box_props                : "
        f"{props or 'NONE (0.10: the terminal fallback will be another prop)'}"
    )

    try:
        world.set_weather(carla.WeatherParameters.ClearNoon)
        say("set_weather              : accepted (no exception)")
    except Exception as exc:  # noqa: BLE001 - we are probing for the type
        say(f"set_weather              : raised {type(exc).__name__}: {exc}")

    if map_name:
        world = client.load_world(map_name)
        say(f"map_name_after_load({map_name}): {world.get_map().name!r}")

    probe_attach(world, carla, say)
    say("=== end probe ===")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carla-host", default="127.0.0.1")
    parser.add_argument("--carla-port", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--map", default="", help="also load this map and report its name"
    )
    parser.add_argument("--out", required=True, help="listing file to write")
    parser.add_argument(
        "--no-measure",
        action="store_true",
        help="skip spawning vehicles to measure dimensions. Every vehicle "
        "row is then written 'unmeasured' and the listing is REFUSED at "
        "load: it can answer 'which blueprint ids does this server have', "
        "which is the day-one question, but it cannot serve the ladder.",
    )
    args = parser.parse_args(argv)

    import carla  # noqa: PLC0415 - only needed when actually listing

    client = carla.Client(args.carla_host, args.carla_port)
    client.set_timeout(args.timeout)
    world = client.get_world()

    probe(client, world, carla, args.map)
    if args.map:
        world = client.get_world()

    library = world.get_blueprint_library()
    rows: List[str] = []
    props: List[str] = []
    unmeasured: List[str] = []
    measurable = 0
    slot = 0
    # The measuring loop. Each vehicle gets its own staging slot and its own
    # verdict: a measurement, or `unmeasured`. There is no third outcome and
    # in particular there is no zero - see measure().
    for blueprint in sorted(library, key=lambda b: b.id):
        category = categorize(blueprint)
        if not category:
            continue
        if category == "prop":
            props.append(blueprint.id)
        dims = None
        if category in MEASURED_CATEGORIES:
            measurable += 1
            if not args.no_measure:
                dims = measure(world, carla, blueprint, slot)
                slot += 1
        row = format_row(blueprint.id, category, dims)
        if category in MEASURED_CATEGORIES and row.endswith(UNMEASURED):
            unmeasured.append(blueprint.id)
        rows.append(row)

    if unmeasured:
        print(
            f"{len(unmeasured)} of {measurable} vehicle/two_wheeler "
            f"blueprint(s) could not be "
            f"measured on this server and are written as {UNMEASURED!r}: "
            f"{', '.join(unmeasured)}",
            file=sys.stderr,
        )
        print(
            "The listing will be refused at load. That is deliberate: a "
            "blueprint with no extents cannot be compared by the ladder's "
            "nearest-dimensions rung, and writing 0.00 instead is what "
            "rendered every NPC of the Belmont Gate C campaign as the same "
            "ambulance.",
            file=sys.stderr,
        )

    # The terminal fallback is recorded, not defaulted, and it is only
    # recorded once this server has confirmed it. If it cannot be confirmed
    # the field is omitted and the listing is refused at load with a message
    # naming this tool - which is the honest outcome, because a listing whose
    # terminal is a guess is what put boxes in front of the driver before.
    fallback = choose_fallback(props)
    if fallback and not verify_on_server(library, fallback):
        print(
            f"{fallback} is in this server's blueprint list but find() does "
            f"not return it; refusing to record it as the terminal fallback.",
            file=sys.stderr,
        )
        fallback = ""

    header = [
        "# blueprint listing written by tools/list_blueprints.py",
        f"# server={client.get_server_version()} map={world.get_map().name}",
    ]
    if fallback:
        header.append(f"# fallback_blueprint: {fallback}")
    header.append(
        "# id\tcategory\tlength\twidth\theight  (vehicles and two-wheelers "
        "only; 'unmeasured' where the measurement failed, never 0.00)"
    )
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(header + rows) + "\n")

    # Fail loudly if the listing cannot serve the ladder, rather than letting
    # the bridge discover it on the first unmatched actor mid-rollout.
    sys.path.insert(0, "src")
    from alpasim_carla.catalog import BlueprintUnavailable, load_catalog

    try:
        catalog = load_catalog(args.out)
    except BlueprintUnavailable as exc:
        print(f"listing written to {args.out} but it cannot serve: {exc}",
              file=sys.stderr)
        return 1
    print(
        f"wrote {args.out}: {len(catalog.vehicles)} vehicles, "
        f"{len(catalog.two_wheelers)} two-wheelers, walker={catalog.walker}, "
        f"fallback_blueprint={catalog.fallback_prop} (verified on this "
        f"server and recorded in the listing). Every vehicle and two-wheeler "
        f"candidate carries measured extents - the load above is what "
        f"establishes that, since it refuses the listing otherwise."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
