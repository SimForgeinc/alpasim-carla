# ADR-BRIDGE-002: A blueprint dimension is measured or refused — it is never zero

Status: accepted, 2026-09-19, after the Belmont Gate C campaign. Supersedes the
deferral recorded at `tools/list_blueprints.py:measure()` on the same day.

**The decision, in one line: a vehicle or two-wheeler row in a blueprint
listing carries a real measurement or the word `unmeasured`, and a listing
containing `unmeasured` — or a `0.00` — is refused at load by name, with the
regeneration command.**

## What a zero cost

The Belmont Gate C campaign of 2026-09-19 ran against a listing with **144 of
145 rows reading 0.00**. `_nearest_by_dims` minimises over the catalog, so the
only row with real extents — `vehicle.ambulance.ford` at 6.36 × 2.35 × 2.43 —
was nearest to everything. All **462 NPC spawn decisions** in the campaign
resolved to that one ambulance, each logged `decision=dims_heuristic[no-label]`.

An 8.388 × 2.823 m `trailer` was drawn as a 6.36 m ambulance. The policy's own
reasoning called it "the stopped ambulance ahead" — it was describing what it
was shown, correctly. The collision scorer and `simforge-closed-loop`'s AABB
cross-check both judged the **declared** 8.39 m box. The geometry that was
judged was not the geometry that was perceived, by two metres of length, and no
verdict computed over that run means what a verdict is supposed to mean. The
full diagnosis is `simforge-closed-loop/evidence/gate_c_belmont_010/COLLISION-DIAGNOSIS.md`.

Nothing warned. A zero is a float in the column a float belongs in.

## The cause, which is not the one that was recorded

The deferral note hypothesised that the extents were read after the actor was
already destroyed. **They were not.** The read sat inside the `try`, above the
`finally` that destroyed; the actor was alive at every read.

What the code actually supports is one line further up: every blueprint in the
library was spawned at the *same* transform, `(0, 0, 500)`, with a single
attempt, and `try_spawn_actor` returns `None` rather than raising when that
point is occupied. That `None` was converted to `(0.0, 0.0, 0.0)` and written
as a measurement.

It fits what was observed, which the old hypothesis did not:
`vehicle.ambulance.ford` sorts first among `vehicle.*`, so it got the free
point; the `attempting to destroy an actor that is already dead: Actor 81
(vehicle.ambulance.ford)` warning names it alone, and says its destroy did not
land where the client thought it did — leaving the point occupied for the 144
blueprints behind it. One actor spawned, one actor warned about, 144 never
spawned at all.

`ActorRegistry._spawn` already staged actors on a grid with four retries,
because one fixed spawn point does not work. The tool never got that treatment.

## The decision

1. **The measurement.** `measure()` stages each blueprint on its own slot of
   the registry's grid, climbs the same four-rung retry ladder, disables
   physics, waits one tick, checks the actor is alive, reads the box, and
   destroys. It returns `Optional[Dims]` — `None`, never a zero, on any
   failure.
2. **The writer** emits `unmeasured` for a `None`, and for anything that would
   format as `0.00`. The guard is on the formatted string, because 4 mm is not
   a vehicle either. Walker and prop rows now carry no numbers at all: they
   used to be written `0.00 0.00 0.00`, which put a column of zeros meaning
   "not applicable" beside a column of zeros meaning "the measurement failed".
   **No listing this tool writes contains the text `0.00`.**
3. **The reader** refuses a listing with any unmeasured or zero vehicle or
   two-wheeler row, naming the count, the first few blueprints and their line
   numbers, what a zero does to the ladder, and the regeneration command.

### Why both halves, and not just one

The writer alone would be enough for listings written from now on. It is not
enough for the listings that exist: the Belmont catalog of zeros is on the GPU
box right now, it parses cleanly today, and any reader that only rejected the
new `unmeasured` token would load it and produce the ambulance campaign again.
The reader is what makes the defect unrepeatable rather than merely fixed.

The writer alone would also let a hand-edited file through, and the reader
alone would leave the generator with nothing honest to write for a blueprint it
could not measure — which is how `0.00` got into the format in the first place.

This mirrors `ADR-BRIDGE-001`: the generator writes a fact only after
establishing it, and the reader refuses a listing that cannot serve the ladder,
by name, with the command that fixes it.

## Consequences

- **Every listing must be regenerated, and every digest moves.** Vehicle rows
  gain real numbers and walker/prop rows lose their zero columns, so
  `catalog_digest` changes for both the 0.10 Belmont listing and the 0.9.16
  twin listing. A run manifest pinning `blueprint_catalog_digest` pins the old
  catalog. A new listing is a new catalog — as in ADR-BRIDGE-001.
- **The old Belmont listing will not load.** This is the intended migration
  path: there is no flag to tolerate it, because tolerating it is what the
  campaign did.
- **`--no-measure` now produces a listing that cannot serve.** It still answers
  the day-one question — which blueprint ids does this server have — and it is
  refused at load rather than silently filling the ladder with zeros.
- **A failure of the spawn fix is visible.** The staging and tick changes are a
  hypothesis about a server this repository's test suite cannot reach. If they
  are wrong, the tool writes `unmeasured` and nothing loads the file. If the
  old code's assumption was wrong, it wrote `0.00` and everything loaded it.
  That asymmetry is the decision; the spawn change is only the repair.
- **What only a live run can settle:** whether a staged spawn succeeds for
  every vehicle blueprint on the 0.10 Belmont image, and whether a freshly
  spawned actor there reports real extents after one tick. The unit suite pins
  the seam — that an unmeasurable blueprint cannot reach the ladder wearing a
  number — in `tests/test_blueprint_dimensions.py`.

Numbering: `ADR-0NN` belongs to `simforge-closed-loop/docs/adr/`. Bridge-local
ADRs carry the `ADR-BRIDGE-` prefix so the two sequences cannot collide.
