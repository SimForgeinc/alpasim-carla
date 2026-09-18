"""Blueprint catalogue: what the fallback ladder is allowed to choose from.

The ladder used to hard-code eight CARLA 0.9.16 vehicle ids, two two-wheelers,
one walker and ``static.prop.box03``. On CARLA 0.10 none of those vehicle ids
exist verbatim, both two-wheeler categories were removed, and several
survivors carry a ``vehicle.ue4.<make>.<model>`` id - so every lookup misses
and the ladder degrades every actor to the prop, or raises if the prop is
missing too.

So the candidates are data, not code. ``tools/list_blueprints.py`` writes a
listing against the server actually in use; this module parses it. There is
no fallback table any more: :func:`default_catalog` raises and names the
generator, because a table that is wrong in every row is worse than no
table at all - it produces a run that renders boxes and scores them.

:func:`catalog_digest` hashes the catalogue as the ladder sees it, so a run
manifest can name the listing it resolved against by content rather than by
filename.

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

import hashlib
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

    for missing, what in (
        (not vehicles, "vehicle blueprint; the ladder cannot place a car-like actor"),
        (not walkers, "walker blueprint; the ladder cannot place a pedestrian"),
        (
            not props,
            "prop blueprint; the ladder has no terminal fallback and an "
            "unmatched actor would raise mid-rollout",
        ),
    ):
        if missing:
            raise BlueprintUnavailable(
                f"{source} lists no {what}. Regenerate the listing against "
                f"the server you are targeting:\n"
                f"    python tools/list_blueprints.py --carla-host HOST "
                f"--carla-port PORT --out {source}"
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


def canonical_listing(catalog: BlueprintCatalog) -> str:
    """Re-emit a catalogue as the listing the ladder would have read.

    Canonical, not verbatim: comments, blank lines, row order between
    categories and the source filename are dropped, because none of them
    change a single choice the ladder makes. What survives is what does -
    the vehicle and two-wheeler candidates in the order nearest-dims
    breaks ties on, the walker, the terminal prop, and every id membership
    is tested against.

    The result parses back through :func:`parse_catalog` to a catalogue
    with the same canonical form, which is what makes the digest stable.
    """
    rows = [
        f"{blueprint_id}\tvehicle\t{dims[0]:.2f}\t{dims[1]:.2f}\t{dims[2]:.2f}"
        for blueprint_id, dims in catalog.vehicles
    ]
    rows += [
        f"{blueprint_id}\ttwo_wheeler\t{dims[0]:.2f}\t{dims[1]:.2f}\t{dims[2]:.2f}"
        for blueprint_id, dims in catalog.two_wheelers
    ]
    rows.append(f"{catalog.walker}\twalker")
    # The terminal prop leads the props so that re-parsing picks the same
    # one back out, whether or not it is the preferred box.
    rows.append(f"{catalog.fallback_prop}\tprop")
    named = {blueprint_id for blueprint_id, _ in catalog.vehicles}
    named |= {blueprint_id for blueprint_id, _ in catalog.two_wheelers}
    named |= {catalog.walker, catalog.fallback_prop}
    rows += [f"{other}\tprop" for other in sorted(catalog.available - named)]
    return "\n".join(rows) + "\n"


def catalog_digest(catalog: BlueprintCatalog) -> str:
    """``sha256:...`` over the catalogue's content, for the run manifest.

    A listing is named by a path, and a path can be regenerated in place
    against a different server; two runs would then claim the same
    catalogue while having resolved different blueprints. The digest is
    the content, so it cannot.
    """
    payload = canonical_listing(catalog).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def default_catalog() -> BlueprintCatalog:
    """There is no default. Raises :class:`BlueprintUnavailable`, always.

    This used to return a curated CARLA 0.9.16 table, and callers reached
    it by simply not passing a catalogue. On 0.10 that table is wrong in
    every row, so the run it silently enabled rendered boxes to the driver
    and scored them - a failure that is only visible in the video.
    """
    raise BlueprintUnavailable(
        "no blueprint listing was supplied; the curated 0.9.16 table is "
        "wrong in every row on 0.10 and is no longer a fallback. Generate "
        "a listing against the server you are targeting and pass it:\n"
        "    python tools/list_blueprints.py --carla-host HOST "
        "--carla-port PORT --out blueprints_0.10.txt\n"
        "    alpasim-carla serve --blueprint-catalog blueprints_0.10.txt ..."
    )
