# ADR-BRIDGE-001: The terminal fallback is a per-image recorded fact, not a code default

Status: accepted, 2026-09-19 (Dib's ruling, before the Belmont Gate C seeds).

**The decision, in one line: the blueprint the ladder degrades an unplaceable
actor to is read from the listing's `fallback_blueprint:` field, written by
`tools/list_blueprints.py` after it has verified that blueprint exists on that
server - never from a constant in this repository.**

Why: `static.prop.box*` returns 24 blueprints on CARLA 0.9.16 and **zero** on
the 0.10 Belmont image
(`ghcr.io/simforgeinc/carla-rfs-munich-belmont@sha256:d1b16b06...`, measured
2026-09-19). `catalog.PREFERRED_PROP = "static.prop.box03"` therefore meant two
different things on two servers while reading like one decision, and on 0.10 it
meant a blueprint that does not exist. `static.prop.advertisement` on 0.10 and
`static.prop.box03` on 0.9.16 are now facts recorded per image, each verified
against the server that was listed.

Consequences:

- The field rides in the listing's comment header (`# fallback_blueprint: <id>`),
  not as a row. A reader that predates the field skips `#` lines unharmed,
  whereas an unknown row category is a parse error - and `simforge-closed-loop`
  reads these listings through this repository's parser.
- A listing **without** the field is refused at load by name, with the
  regeneration command - not silently defaulted. There is no guess to fall back
  to; that is the point.
- A listing whose declared id has no prop row of its own is refused too: the
  generator only writes the field after verifying, so a mismatch means the file
  was hand-edited and its claim is unverified.
- The listing format changed, so **every listing's sha256 changes**. A run
  manifest pinning `blueprint_catalog_digest` pins the old catalog; regenerate
  the listing per image and record the new digest. A new listing is a new
  catalog.

Numbering: `ADR-0NN` belongs to `simforge-closed-loop/docs/adr/` (ADR-015,
ADR-017 are cited from this repository). Bridge-local ADRs carry the
`ADR-BRIDGE-` prefix so the two sequences cannot collide.
