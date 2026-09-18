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
not use dims for them.

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
exists to serve as the ladder's terminal fallback, and whether set_weather
raises or is tolerated.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Tuple


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
    """Spawn at altitude, read the bounding box, destroy. (0,0,0) on failure."""
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
    say(f"box_props                : {props or 'NONE (ladder has no box!)'}")

    try:
        world.set_weather(carla.WeatherParameters.ClearNoon)
        say("set_weather              : accepted (no exception)")
    except Exception as exc:  # noqa: BLE001 - we are probing for the type
        say(f"set_weather              : raised {type(exc).__name__}: {exc}")

    if map_name:
        world = client.load_world(map_name)
        say(f"map_name_after_load({map_name}): {world.get_map().name!r}")
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
    for blueprint in sorted(library, key=lambda b: b.id):
        category = categorize(blueprint)
        if not category:
            continue
        if category in ("vehicle", "two_wheeler") and not args.no_measure:
            length, width, height = measure(world, carla, blueprint)
        else:
            length, width, height = (0.0, 0.0, 0.0)
        rows.append(
            f"{blueprint.id}\t{category}\t{length:.2f}\t{width:.2f}\t{height:.2f}"
        )

    header = [
        "# blueprint listing written by tools/list_blueprints.py",
        f"# server={client.get_server_version()} map={world.get_map().name}",
        "# id\tcategory\tlength\twidth\theight",
    ]
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
        f"fallback={catalog.fallback_prop}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
