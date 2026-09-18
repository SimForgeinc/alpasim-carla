"""Blueprint catalogue: what the fallback ladder is allowed to choose from.

The ladder used to hard-code eight CARLA 0.9.16 vehicle ids, two two-wheelers,
one walker and ``static.prop.box03``. On CARLA 0.10 none of those vehicle ids
exist verbatim, both two-wheeler categories were removed, and several
survivors carry a ``vehicle.ue4.<make>.<model>`` id - so every lookup misses
and the ladder degrades every actor to the prop, or raises if the prop is
missing too.

So the candidates are data, not code. ``tools/list_blueprints.py`` writes a
listing against the server actually in use; this module parses it. The
curated 0.9.16 table remains as :func:`default_catalog` for stock twins.

Listing format - tab-separated, ``#`` comments ignored::

    # id	category	length	width	height
    vehicle.lincoln.mkz	vehicle	4.90	2.13	1.51
    walker.pedestrian.0001	walker	0.0	0.0	0.0
    static.prop.box03	prop	0.0	0.0	0.0

Categories are ``vehicle``, ``two_wheeler``, ``walker`` and ``prop``. Sizes are
length/width/height in meters, measured from a spawned actor's bounding box;
only vehicles and two-wheelers use them (nearest-dims selection ignores
height).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set, Tuple

Dims = Tuple[float, float, float]
Candidate = Tuple[str, Dims]

PREFERRED_PROP = "static.prop.box03"


class BlueprintUnavailable(RuntimeError):
    """A blueprint the ladder structurally depends on is not on this server.

    Raised at catalogue load, not mid-rollout: a missing terminal fallback
    used to surface as an ``IndexError`` out of ``ActorRegistry._spawn``,
    which under ``BATCH_RENDER_RGB`` aborts the whole rollout on the first
    frame that needs it.
    """


@dataclass
class BlueprintCatalog:
    vehicles: List[Candidate] = field(default_factory=list)
    two_wheelers: List[Candidate] = field(default_factory=list)
    walker: str = ""
    fallback_prop: str = ""
    available: Set[str] = field(default_factory=set)
    source: str = "built-in 0.9.16 table"

    def has(self, blueprint_id: str) -> bool:
        return blueprint_id in self.available


def parse_catalog(text: str, source: str = "<string>") -> BlueprintCatalog:
    """Parse a blueprint listing. Raises on a catalogue that cannot serve."""
    vehicles: List[Candidate] = []
    two_wheelers: List[Candidate] = []
    walkers: List[str] = []
    props: List[str] = []
    available: Set[str] = set()

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("\t")
        if len(parts) < 2:
            raise ValueError(
                f"{source} line {lineno}: expected at least 'id<TAB>category', "
                f"got {stripped!r}"
            )
        blueprint_id, category = parts[0].strip(), parts[1].strip()
        available.add(blueprint_id)

        if category in ("vehicle", "two_wheeler"):
            if len(parts) < 5:
                raise ValueError(
                    f"{source} line {lineno}: {category} rows need "
                    f"id/category/length/width/height, got {stripped!r}"
                )
            try:
                dims = (float(parts[2]), float(parts[3]), float(parts[4]))
            except ValueError as exc:
                raise ValueError(
                    f"{source} line {lineno}: non-numeric dimensions in "
                    f"{stripped!r}"
                ) from exc
            (vehicles if category == "vehicle" else two_wheelers).append(
                (blueprint_id, dims)
            )
        elif category == "walker":
            walkers.append(blueprint_id)
        elif category == "prop":
            props.append(blueprint_id)
        else:
            raise ValueError(
                f"{source} line {lineno}: unknown category {category!r} "
                f"(expected vehicle, two_wheeler, walker or prop)"
            )

    if not vehicles:
        raise BlueprintUnavailable(
            f"{source} lists no vehicle blueprint; the ladder cannot place a "
            f"car-like actor."
        )
    if not walkers:
        raise BlueprintUnavailable(
            f"{source} lists no walker blueprint; the ladder cannot place a "
            f"pedestrian."
        )
    if not props:
        raise BlueprintUnavailable(
            f"{source} lists no prop blueprint; the ladder has no terminal "
            f"fallback and an unmatched actor would raise mid-rollout."
        )

    fallback = PREFERRED_PROP if PREFERRED_PROP in props else props[0]
    return BlueprintCatalog(
        vehicles=vehicles,
        two_wheelers=two_wheelers,
        walker=walkers[0],
        fallback_prop=fallback,
        available=available,
        source=source,
    )


def load_catalog(path: str) -> BlueprintCatalog:
    with open(path, "r", encoding="utf-8") as handle:
        return parse_catalog(handle.read(), source=path)


def default_catalog() -> BlueprintCatalog:
    """The curated CARLA 0.9.16 table the ladder shipped with.

    Approximate stock dimensions (length, width, height in meters). Correct
    for stock 0.9.16 twins; wrong for 0.10, which is why a listing file
    overrides it.
    """
    vehicles: List[Candidate] = [
        ("vehicle.mini.cooper_s", (3.80, 1.92, 1.45)),
        ("vehicle.audi.tt", (4.18, 1.99, 1.39)),
        ("vehicle.tesla.model3", (4.69, 2.09, 1.49)),
        ("vehicle.mercedes.coupe_2020", (4.79, 2.04, 1.45)),
        ("vehicle.audi.etron", (4.90, 2.03, 1.62)),
        ("vehicle.nissan.patrol_2021", (5.08, 2.18, 1.93)),
        ("vehicle.ford.ambulance", (6.34, 2.39, 2.55)),
        ("vehicle.carlamotors.firetruck", (8.49, 2.94, 3.41)),
    ]
    two_wheelers: List[Candidate] = [
        ("vehicle.diamondback.century", (1.66, 0.42, 1.04)),
        ("vehicle.yamaha.yzf", (2.19, 0.81, 1.16)),
    ]
    walker = "walker.pedestrian.0001"
    available = {bp for bp, _ in vehicles} | {bp for bp, _ in two_wheelers}
    available |= {walker, PREFERRED_PROP}
    return BlueprintCatalog(
        vehicles=vehicles,
        two_wheelers=two_wheelers,
        walker=walker,
        fallback_prop=PREFERRED_PROP,
        available=available,
        source="built-in 0.9.16 table",
    )
