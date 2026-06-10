# alpasim-carla — PLAN

**Mission.** A small, public, Apache-2.0 library that implements NVIDIA
AlpaSim's renderer contract (`SensorsimService`, gRPC/protobuf) backed by
CARLA. The promise to a stranger on the internet: *point this at your CARLA
server, point AlpaSim's config at this bridge, and any AlpaSim driver policy
(Alpamayo 1.5, Transfuser, your own) drives closed-loop inside CARLA worlds —
with AlpaSim's runtime, controller, physics, and scorers unchanged.*

Pins (stated everywhere, verified on the test bed):
AlpaSim commit `a1f05bb628f3d1d19d79d44188e836e9108f98c6` / proto v0 /
`alpasim_grpc` 0.54.0 · CARLA **0.9.16** · bridge Python **3.10.x** (CARLA
client wheel), AlpaSim Python 3.12 · tested on A100 (Ubuntu 22.04 host,
CARLA in docker, `-RenderOffScreen`).

---

## 1. Teaching section — how this all works

*(Written for a contributor who knows neither protobuf nor AlpaSim.)*

### Protobuf and gRPC in one paragraph

A `.proto` file declares typed messages (field names, numbers, types) and
services (named RPCs with request/response message types). `protoc` compiles
that declaration into Python classes that serialize to a compact, stable wire
format; gRPC then exposes the service over HTTP/2 so a *client stub* in one
process can call a *servicer* implementation in another — possibly written in
a different language or, as here, running a different Python version. The
`.proto` files are the contract; both sides only need to agree on them.
AlpaSim ships its protos in `alpasim_grpc/v0/`; we vendor exact copies (see
`proto/README.md`) and never edit them.

### AlpaSim's closed loop

AlpaSim's **runtime** is the single owner of world state. Every tick it asks
each service a question and composes the answers:

```
            ┌────────────────────────────────────────────────────────┐
            │                     AlpaSim RUNTIME                    │
            │      (owns all object/ego trajectories and time)       │
            └──┬──────────────────┬──────────────────────┬───────────┘
   "objects are HERE,             │                      │
    camera is HERE —     "here are frames,      "apply this plan →
    give me frames"       give me a plan"        new ego pose"
               │                  │                      │
               ▼                  ▼                      ▼
        ┌────────────┐     ┌────────────┐    ┌─────────────────────┐
        │  RENDERER  │     │   DRIVER   │    │ CONTROLLER/PHYSICS  │
        │ (this lib) │     │ (Alpamayo…)│    │  (vehicle model)    │
        └────────────┘     └────────────┘    └─────────────────────┘
               └────────────── repeat every tick ─────────────┘
```

Per camera trigger the runtime sends `render_rgb`: where every object is
(`dynamic_objects`: track id + pose pair), where the camera is
(`sensor_pose` + `camera_intrinsics`), and the time window
(`frame_start_us`/`frame_end_us`). It feeds the returned frames to the
driver policy, gets a trajectory plan back, runs the controller + vehicle
model to advance the ego pose, and repeats.

### The puppet theater (what the CARLA side is and is NOT)

**AlpaSim moves the puppets; CARLA takes the photo.** The bridge teleports
CARLA actors to exactly the poses in each request (`actor.set_transform`,
physics and autopilot OFF), places the camera, ticks once, captures, returns
encoded bytes. CARLA must never simulate object motion itself — two owners of
state means divergence. The bridge's only cross-call memory is the track-id
registry: unseen id → spawn; known id → teleport; id absent → despawn.

### Why two Pythons (and why nobody fights it)

AlpaSim needs Python 3.12; CARLA's client wheel needs 3.10. Because the
boundary is gRPC, the bridge runs as its own 3.10 process. The only piece
installed inside AlpaSim's 3.12 env is `alpasim-carla-configs` — pure YAML +
an `alpasim.configs` entry point that makes `renderer=carla` a wizard flag.

---

## 2. Verified contract ground truth

Sources of truth (and the only ones): (a) the pinned protos, (b) replayed
`.asl` traffic, (c) the vendored runtime source. Anything not derivable from
these is in `OPEN_QUESTIONS.md`, not in the code.

* The 8 RPCs: `render_rgb`, `render_lidar`, `render_aggregated`,
  `get_version`, `get_available_scenes`, `get_available_cameras`,
  `get_available_trajectories`, `get_available_ego_masks`.
* Real traffic (732-request production rollout decoded): `render_rgb` per
  camera per step; one `get_available_cameras` + one
  `get_available_ego_masks` per session; startup probes `get_version` +
  `get_available_scenes` (scene must be listed, `"*"` wildcard honored);
  `get_available_trajectories` never called; `render_aggregated` exists but
  is unused at this commit (`use_aggregated_render=False` default, and its
  consumption path doesn't match the generated stubs).
* `DynamicObject` = `{track_id, pose_pair}` only — bbox dims and labels live
  in `RolloutMetadata.actor_definitions` (.asl) and in our scene manifests.
* Frames: `local` = right-handed ENU z-up; `rig`/`aabb` = x-fwd/y-left/z-up
  (aabb origin = bbox center); cameras = CV optical (x-right/y-down/z-fwd);
  quats `(w,x,y,z)`; active transforms; standard SE(3) composition (verified
  empirically against `alpasim_utils.geometry.Pose`); µs timestamps.
* Cameras in real traffic are **ftheta** (hyperion rig), native 1080×1920,
  requested at 1080×1900 (center-crop semantics assumed → CONTRACT.md),
  JPEG q95, rolling shutter.
* `get_version.grpc_api_version` must echo `alpasim_grpc` **0.54.0**.
* Camera catalog: the renderer's `get_available_cameras` is the source of
  truth; local runtime config may modify but NOT add cameras → our manifests
  must serve every logical id the driver uses.
* Wiring: `wizard.external_services: dict[str, list[str]]` + dropping
  `renderer` from `wizard.run_sim_services` (the
  `deploy/external_video_model.yaml` pattern); `renderer:` is an optional
  Hydra group in base defaults → our entry-point package ships
  `renderer/carla.yaml`.

## 3. Architecture

```
src/alpasim_carla/
  _proto/      generated stubs (namespaced; never collides with alpasim_grpc)
  frames.py    pure coordinate math: ENU↔UE, quat↔rotator, optical frame,
               bbox-center offsets, scene anchoring   ← golden-tested first
  cameras.py   CameraSpec → CARLA pinhole FOV; explicit UnsupportedCameraError;
               --allow-pinhole-approximation is the ONLY degradation path
  aslio.py     .asl reader (4-byte BE length + LogEntry)
  scenes.py    scene manifests (YAML): scene_id → CARLA map, camera rig,
               actor table, anchor; manifest_from_asl()
  registry.py  track-id → CARLA actor lifecycle (spawn/teleport/despawn)
  world.py     CarlaBackend: sync mode, sensor pool, tick-once-capture
  lifecycle.py CARLA server launcher (docker, production-proven flags)
  server.py    SensorsimServicer (all 8 RPCs) + SyntheticBackend
  cli.py       alpasim-carla serve / scene-from-asl / launch-carla
configs_pkg/   alpasim-carla-configs (alpasim.configs entry point)
proto/         pristine vendored protos + attribution
tools/         replay_contract.py (G0) · replay_render.py (G2) · gen_protos.sh
scenes/examples/  example scene manifests on stock towns
docs/CONTRACT.md  the per-RPC contract spine
evidence/<gate>/  gate artifacts
```

Error policy (no guessing, no silent fallbacks): unknown scene → NOT_FOUND
listing available scenes; unsupported camera model/distortion/shutter →
INVALID_ARGUMENT naming the field and alternatives unless
`--allow-pinhole-approximation`; unmappable object label → documented box
prop fallback + structured warning (never a silent skip); lidar on the CARLA
backend → UNIMPLEMENTED (v0.1 fence).

## 4. Validation gates

Each gate = exact command + artifact under `evidence/<gate>/`; a milestone is
done only when its gate passes.

* **G0 — contract replay (no CARLA).**
  `python tools/replay_contract.py --asl <rollout.asl> --report evidence/g0/replay_report.json`
  Streams every recorded sensorsim request to the synthetic servicer;
  startup probes mirror `alpasim_runtime.validation`; 100% of requests get
  valid responses (decode, exact resolution, requested encoding); all 8 RPCs
  answer; exit code is the gate.
* **G1 — frame math.**
  `.venv-g1/bin/pytest tests/ -m "not carla"` in a venv **without** the
  `carla` package. Hand-computed fixtures, recorded-rig fixtures,
  alpasim→carla→alpasim round-trip ≤1e-5, intrinsics→FOV cases (90°
  pinhole, 43.6° tele, recorded ftheta poly → 120°).
* **G2 — CARLA renders replayed traffic.**
  CARLA via the same base image/flags as SimForge's production workers, GPU
  0/1, non-default port. `python tools/replay_render.py --asl …
  --allow-pinhole-approximation --metrics evidence/g2/metrics.json
  --contact-sheet evidence/g2/contact_sheet.jpg`
  Scripted: every response decodes at the requested resolution;
  bridge-managed actor count == `len(dynamic_objects)` after every request;
  re-sending an identical request reproduces actor transforms within
  1 cm / 0.1°; p95 `render_rgb` latency recorded.
* **G3 — closed loop end-to-end.**
  Bridge serving an example scene; own 3.12 venv with AlpaSim installed from
  the pinned checkout + `alpasim-carla-configs`;
  `alpasim_wizard deploy=local topology=1gpu driver=alpamayo1 renderer=carla
  'wizard.external_services.renderer=["<host>:50051"]' wizard.log_dir=…`
  (physics skipped: `runtime.endpoints.physics.skip=true`,
  `runtime.simulation_config.physics_update_mode=NONE`). Gate: rollout
  completes; `.asl` + scorer outputs exist; ego displacement > 10 m; rendered
  video artifact. Run dir copied to `evidence/g3/`.
* **G4 — stranger test.**
  Fresh clone + fresh venvs; README quickstart copy-paste reproduces G3;
  transcript + `pip install -e .` + simulator-free suite green ⇒ tag
  `v0.1.0`.

## 5. Scope fences (v0.1)

**In:** `render_rgb`, camera-only `render_aggregated`, all discovery RPCs,
pinhole cameras (+ explicit ftheta/fisheye approximation), example scenes on
stock towns, scene-from-asl tool, Docker, teaching docs.
**Out (roadmap):** lidar, distortion post-warp, rolling-shutter simulation,
multi-rollout instance pooling, CARLA-backed TrafficService/physics, Windows,
native CARLA-recorded runtime scenes (G3 reuses AlpaSim's own scene catalog
for session seeding; the bridge maps those scene ids onto CARLA towns).

## 6. Risks

1. ftheta→pinhole approximation degrades the alpamayo policy (G3 only
   requires >10 m displacement; FOV matched from the recorded polynomial).
2. CARLA repeatability — fixed weather/seed, transforms compared not pixels.
3. Wizard DOCKER_COMPOSE assumptions on the box — smoke with driver=manual
   before alpamayo1.
4. Request-resolution ≠ intrinsics-resolution semantics — center-crop
   documented; OPEN_QUESTIONS.md.
5. Sensor frame/number mismatch — frame-id matched capture, pooled sensors.
6. Port/GPU collisions with production services — non-default ports, GPUs
   0/1 only, GraphicsAdapter pinning.
7. Off-center principal points unrepresentable in CARLA — tolerance + flag.
8. alpamayo checkpoint cache/auth in the driver container — verified before
   G3.
