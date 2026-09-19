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

Listing format - tab-separated rows, ``#`` comments ignored except for the
``fallback_blueprint:`` field::

    # fallback_blueprint: static.prop.box03
    # id	category	length	width	height
    vehicle.lincoln.mkz	vehicle	4.90	2.13	1.51
    walker.pedestrian.0001	walker	0.0	0.0	0.0
    static.prop.box03	prop	0.0	0.0	0.0

Categories are ``vehicle``, ``two_wheeler``, ``walker`` and ``prop``. Sizes are
length/width/height in meters, measured from a spawned actor's bounding box;
only vehicles and two-wheelers use them (nearest-dims selection ignores
height).

``fallback_blueprint:`` names the terminal fallback - the blueprint an actor
the ladder cannot otherwise place degrades to. It is **read**, never chosen
here, because it is a per-image fact: ``static.prop.box03`` exists on CARLA
0.9.16 and does not exist at all on the 0.10 Belmont image, where
``static.prop.advertisement`` is the recorded terminal. A code default would
have meant a different blueprint on each server while looking like one
decision. ``tools/list_blueprints.py`` writes the field after verifying the
blueprint exists on the server it listed; see
``docs/adr/ADR-BRIDGE-001-terminal-fallback-is-a-recorded-fact.md``.

It rides in the comment header rather than as a row on purpose: a reader
that predates the field skips ``#`` lines and is unharmed, whereas an
unknown row category is a parse error. A listing WITHOUT the field is
refused by name - see :func:`parse_catalog` - rather than falling back to a
guess.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List, Set, Tuple

Dims = Tuple[float, float, float]
Candidate = Tuple[str, Dims]

#: The comment field carrying the terminal fallback. There is deliberately
#: no constant naming a blueprint here: that constant was
#: ``PREFERRED_PROP = "static.prop.box03"``, and on the 0.10 Belmont image
#: that blueprint does not exist (``static.prop.box*`` returns zero
#: blueprints), so the ladder silently meant something different per server.
FALLBACK_FIELD = "fallback_blueprint"


def _regenerate(source: str) -> str:
    return (
        "Regenerate the listing against the server you are targeting:\n"
        f"    python tools/list_blueprints.py --carla-host HOST "
        f"--carla-port PORT --out {source}"
    )


def _declared_fallback(comment: str) -> str:
    """The id on a ``# fallback_blueprint: <id>`` line, or ``""``."""
    body = comment.lstrip("#").strip()
    prefix = FALLBACK_FIELD + ":"
    if not body.startswith(prefix):
        return ""
    return body[len(prefix):].strip()


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
    declared = ""

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            named = _declared_fallback(stripped)
            if named and declared and named != declared:
                raise ValueError(
                    f"{source} line {lineno}: a second '{FALLBACK_FIELD}:' "
                    f"names {named!r} after {declared!r}; one listing "
                    f"describes one server and has one terminal fallback"
                )
            declared = named or declared
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
                f"{source} lists no {what}. " + _regenerate(source)
            )

    if not declared:
        raise BlueprintUnavailable(
            f"{source} declares no '{FALLBACK_FIELD}:' field, so the "
            f"terminal fallback is unknown. It is not guessed here: "
            f"static.prop.box03 exists on CARLA 0.9.16 and does not exist "
            f"on the 0.10 Belmont image, so any default this reader picked "
            f"would silently mean a different blueprint per server. A "
            f"listing generated before the field existed is exactly this "
            f"case and has to be rewritten, not patched by hand. "
            + _regenerate(source)
        )
    if declared not in props:
        raise BlueprintUnavailable(
            f"{source} declares '{FALLBACK_FIELD}: {declared}' but lists no "
            f"prop row for it, so the listing disagrees with itself. "
            f"tools/list_blueprints.py writes that field only after "
            f"verifying the blueprint exists on the server it listed, so a "
            f"mismatch means the file was edited by hand. "
            + _regenerate(source)
        )

    fallback = declared
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

    Canonical, not verbatim: blank lines, row order between categories,
    the source filename and every comment EXCEPT the
    ``fallback_blueprint:`` declaration are dropped, because none of them
    change a single choice the ladder makes. What survives is what does -
    the vehicle and two-wheeler candidates in the order nearest-dims
    breaks ties on, the walker, the declared terminal prop, and every id
    membership is tested against. The declaration survives because it is
    data: it is the only thing that says which prop the ladder degrades
    to on this server.

    The result parses back through :func:`parse_catalog` to a catalogue
    with the same canonical form, which is what makes the digest stable.
    """
    rows = [f"# {FALLBACK_FIELD}: {catalog.fallback_prop}"]
    rows += [
        f"{blueprint_id}\tvehicle\t{dims[0]:.2f}\t{dims[1]:.2f}\t{dims[2]:.2f}"
        for blueprint_id, dims in catalog.vehicles
    ]
    rows += [
        f"{blueprint_id}\ttwo_wheeler\t{dims[0]:.2f}\t{dims[1]:.2f}\t{dims[2]:.2f}"
        for blueprint_id, dims in catalog.two_wheelers
    ]
    rows.append(f"{catalog.walker}\twalker")
    # The terminal prop still leads the props, so the canonical form reads
    # the same way it used to; what makes re-parsing pick it back out is
    # the declaration above, not this position.
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
