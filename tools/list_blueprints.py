#!/usr/bin/env python
"""Day-one check: list what this CARLA server can actually spawn.

Writes the blueprint listing that alpasim_carla.catalog reads, so the fallback
ladder is filled in from the server in front of us rather than from a curated
CARLA 0.9.16 table. On 0.10 that table is wrong in every row: none of the
eight vehicle ids exist verbatim, both two-wheeler categories were removed,
and several survivors carry a ``vehicle.ue4.<make>.<model>`` id.

Dimensions are not available from a blueprint - only a spawned actor has a
bounding box - so each vehicle is spawned once at altitude, measured and
destroyed. Walkers and props are listed without dimensions; the ladder does
not use dims for them. (On 0.10 the measuring loop is known to return zeros
after the first vehicle - see :func:`measure`. Deferred by ruling, not
missed.)

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
from typing import List, Tuple


#: The tool's preference when the server has it, and nothing more. It is a
#: SELECTION RULE here, not a fallback the ladder carries: whatever wins is
#: verified on the server and written into the listing as a fact about that
#: image. On 0.9.16 this id exists and is recorded; on the 0.10 Belmont
#: image `static.prop.box*` returns zero blueprints, so the first prop in
#: id order is recorded instead - which is how
#: `fallback=static.prop.advertisement` came out of this tool on Belmont.
PREFERRED_FALLBACK = "static.prop.box03"


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


def measure(world, carla, blueprint) -> Tuple[float, float, float]:
    """Spawn at altitude, read the bounding box, destroy. (0,0,0) on failure.

    KNOWN BROKEN ON CARLA 0.10 - DEFERRED BY RULING, NOT MISSED.

    Symptom, measured on the Belmont image on 2026-09-19: the generated
    listing had **144 of 145 rows reading length 0.00**. Only
    ``vehicle.ambulance.ford``, the first vehicle spawned, carried real
    extents (6.36 x 2.35 x 2.43). The run also printed

        WARNING: attempting to destroy an actor that is already dead:
                 Actor 81 (vehicle.ambulance.ford)

    Likely cause: the dimensions are read after the actor is already gone.
    ``bounding_box`` is a property on a client-side actor handle, and on
    0.10 that handle appears not to survive the spawn/destroy cycle this
    function runs per blueprint, so every subsequent read returns a
    zeroed box rather than raising. The `finally` destroy firing on an
    actor the server already reaped is the same symptom from the other
    side.

    What a catalog of zeros affects:
      * G2's nearest-dimensions rung - every candidate is (0,0,0), so the
        "nearest" vehicle is whichever one sorts first, not the one that
        fits;
      * the blueprint audit, which resolves gated actors through that same
        rung.
    What it does NOT affect:
      * the AABB collision cross-check in simforge-closed-loop, which reads
        extents from the rollout log and never opens the catalog;
      * Belmont Gate C, whose Stage C scene declares ``traffic: none``, so
        no NPC is ever chosen or audited.

    Deferred deliberately (Dib, 2026-09-19): it does not gate the Gate C
    seeds, and it MUST be fixed before any Stage B scene package, where
    NPCs exist and both readers above matter.
    """
    transform = carla.Transform(carla.Location(x=0.0, y=0.0, z=500.0))
    actor = world.try_spawn_actor(blueprint, transform)
    if actor is None:
        return (0.0, 0.0, 0.0)
    try:
        extent = actor.bounding_box.extent
        return (2 * extent.x, 2 * extent.y, 2 * extent.z)
    except (AttributeError, RuntimeError):
        return (0.0, 0.0, 0.0)
    finally:
        try:
            actor.destroy()
        except RuntimeError:
            pass


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
        help="skip spawning vehicles to measure dimensions (writes zeros, "
        "which makes nearest-dims selection meaningless)",
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
    # The measuring loop. Its dimensions are zero for all but the first
    # vehicle on CARLA 0.10 - see measure() for the symptom, the cause and
    # why the fix is deferred rather than missing.
    for blueprint in sorted(library, key=lambda b: b.id):
        category = categorize(blueprint)
        if not category:
            continue
        if category == "prop":
            props.append(blueprint.id)
        if category in ("vehicle", "two_wheeler") and not args.no_measure:
            length, width, height = measure(world, carla, blueprint)
        else:
            length, width, height = (0.0, 0.0, 0.0)
        rows.append(
            f"{blueprint.id}\t{category}\t{length:.2f}\t{width:.2f}\t{height:.2f}"
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
    header.append("# id\tcategory\tlength\twidth\theight")
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
        f"server and recorded in the listing)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
