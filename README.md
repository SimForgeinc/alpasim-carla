# alpasim-carla

A CARLA-backed renderer for [NVIDIA AlpaSim](https://github.com/NVIDIA/alpasim).
It implements AlpaSim's `SensorsimService` gRPC contract, so an AlpaSim driver
policy (Alpamayo 1.5, Transfuser, your own) can drive closed-loop in CARLA
worlds without any changes to AlpaSim's runtime, controller, physics, or
scorers.

**Pins:** AlpaSim commit `a1f05bb628f3` (proto v0, `alpasim_grpc` 0.54.0) ·
CARLA 0.9.16 · Python 3.10 (bridge) / 3.12 (AlpaSim) · tested on NVIDIA A100
with CARLA in Docker (`-RenderOffScreen`). License: Apache-2.0.

## How it works

If you already know AlpaSim, the one-line summary: this is an out-of-process
`SensorsimService` implementation; AlpaSim dictates every pose, CARLA renders
them. If you don't, read on — this section assumes no prior knowledge of
protobuf, AlpaSim, or CARLA internals.

### Protobuf and gRPC in one paragraph

A `.proto` file declares typed messages (fields, types, numbers) and services
(named remote calls with request/response message types). `protoc` compiles it
into Python classes that serialize to a compact wire format; gRPC then serves
those calls over HTTP/2 so a client in one process can call a server in
another — across languages or, as here, across Python versions. The `.proto`
files are the entire contract. AlpaSim's renderer contract is
`SensorsimService` (8 RPCs, vendored under `proto/alpasim_grpc/v0/`); this
library is a server that fulfills it.

### The full picture

AlpaSim is not one program — it is a set of services, each its own
process/container, composed and launched by `alpasim_wizard` (a Hydra CLI).
Every arrow below is a gRPC call.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           AlpaSim  (Python 3.12)                             │
│                                                                              │
│                      ┌─────────────────────────────────┐                     │
│                      │             RUNTIME             │                     │
│                      │  the single owner of the world: │                     │
│                      │  • simulation clock (µs)        │                     │
│                      │  • ego pose history             │                     │
│                      │  • traffic trajectories         │                     │
│                      │  • camera trigger schedule      │                     │
│                      │  • logs everything to .asl      │                     │
│                      └──┬─────────┬─────────┬───────┬──┘                     │
│        render_rgb       │         │         │       │                        │
│        get_available_*  │  drive()│  run_controller_ │ simulate()            │
│        get_version      │         │  and_vehicle()   │                       │
│            │            │         ▼         ▼        ▼                       │
│            │            │  ┌───────────┐ ┌─────────────┐ ┌────────────┐      │
│            │            │  │  DRIVER   │ │ CONTROLLER  │ │ TRAFFICSIM │      │
│            │            │  │ the policy│ │ MPC tracker │ │ simulates  │      │
│            │            │  │ (Alpamayo,│ │ + vehicle   │ │ or replays │      │
│            │            │  │ Transfuser│ │ dynamics    │ │ traffic    │      │
│            │            │  │ …) on GPU │ │ model       │ │ (optional) │      │
│            │            │  └───────────┘ └─────────────┘ └────────────┘      │
│            │            │                                                    │
│            │            │  PHYSICS service (terrain-height queries) exists   │
│            │            │  too, but it loads NVIDIA per-scene artifacts, so  │
│            │            │  CARLA runs skip it (flat-ground assumption).      │
└────────────┼────────────┼────────────────────────────────────────────────────┘
             │ gRPC: SensorsimService on :50051
             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    alpasim-carla bridge  (Python 3.10)                       │
│                                                                              │
│  the render_rgb pipeline, in order:                                          │
│   1. server.py    validate request; explicit errors only (unknown scene →    │
│                   NOT_FOUND with the available list, unsupported camera →    │
│                   INVALID_ARGUMENT naming the field)                         │
│   2. scenes.py    scene_id → manifest: which CARLA map, the camera rig,      │
│                   the actor table (labels + bbox dims), the world anchor     │
│   3. registry.py  diff request.dynamic_objects against live CARLA actors:    │
│                     unseen track_id → spawn   (blueprint from label + dims)  │
│                     known  track_id → set_transform (teleport)               │
│                     absent track_id → destroy                                │
│   4. cameras.py   CameraSpec → CARLA pinhole FOV (ftheta/fisheye only with   │
│                   the explicit --allow-pinhole-approximation flag)           │
│   5. frames.py    convert every pose: ENU right-handed → Unreal left-handed, │
│                   optical camera axes → UE camera axes, bbox-center →        │
│                   actor-pivot offset                                         │
│   6. world.py     place the pooled RGB sensor → world.tick() once → take     │
│                   the frame with that tick's id → encode JPEG/PNG            │
└────────────┬─────────────────────────────────────────────────────────────────┘
             │ CARLA client API (the 0.9.16 wheel matching your server build)
             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    CARLA 0.9.16 server  (Unreal Engine)                      │
│  synchronous mode, fixed weather/seed; physics & autopilot OFF for every     │
│  bridge-managed actor. CARLA renders exactly the state AlpaSim dictated —    │
│  it never simulates object motion itself. Two owners of state = divergence. │
└──────────────────────────────────────────────────────────────────────────────┘
```

The mental model for the CARLA side: **AlpaSim moves the puppets, CARLA takes
the photo.** The bridge's only memory between calls is the track-id registry
in step 3.

### One control step, end to end

At the default 10 Hz control rate, every 100 ms of simulated time looks like
this (4 cameras for the Alpamayo drivers):

```
 RUNTIME                BRIDGE + CARLA              DRIVER            CONTROLLER
    │
    │ interpolate ego + traffic poses at the camera trigger window
    │
    │ render_rgb(cam 1) ──▶ sync actors, place
    │ render_rgb(cam 2) ──▶ camera, tick once,
    │ render_rgb(cam 3) ──▶ capture, encode
    │ render_rgb(cam 4) ──▶
    │ ◀── image_bytes ×4 ──
    │
    │ submit images + ego-motion history ─────▶ policy forward
    │ ◀──────── planned trajectory ─────────── pass (GPU)
    │
    │ run_controller_and_vehicle(plan) ──────────────────────────▶ MPC tracks
    │ ◀──────────── new ego pose ──────────────────────────────── the plan,
    │                                                             vehicle model
    │ advance clock, append to .asl, repeat                       integrates
```

Note what the bridge does *not* do: it never integrates motion, never decides
where anything is, never advances time. Each `render_rgb` request is complete
and self-describing — object poses, camera pose, intrinsics, time window,
output format.

### Session startup

Before the loop starts, the runtime probes the renderer:

1. `get_version` — must report the pinned contract version
   (`grpc_api_version` = `alpasim_grpc` 0.54.0).
2. `get_available_scenes` — the configured `scene_id` must be in the returned
   list (or the renderer may advertise the `"*"` wildcard).
3. `get_available_cameras(scene_id)` — the rig the bridge serves from the
   scene manifest. This is authoritative: AlpaSim's camera config can *modify*
   cameras the renderer reports but cannot *add* ones, so the manifest must
   cover every logical id the driver uses.
4. `get_available_ego_masks` — v0.1 publishes none, which makes the runtime
   disable ego-hood masking; `get_available_trajectories` is never called by
   the runtime at the pinned commit.

Scene data is split deliberately: the **runtime** seeds the session (ego start
pose, route, ground-truth trajectory for scoring) from AlpaSim's own scene
catalog, while the **bridge** only needs its manifest to know what world to
show for that `scene_id` — which CARLA town, where to anchor the recorded
local frame in it, and what each track id looks like.

### Coordinate systems

Every pose crossing the boundary goes through `frames.py` (pure functions,
golden-tested):

| Frame | Convention | Used for |
|---|---|---|
| AlpaSim `local` | right-handed ENU, z-up, meters | all request poses |
| AlpaSim `rig` / `aabb` | x-forward, y-left, z-up; `aabb` origin = bbox center | object poses (`aabb`), camera mounts (`rig`) |
| AlpaSim camera | CV optical: x-right, y-down, z-forward | `sensor_pose` |
| Unreal / CARLA | left-handed, x-forward, y-right, z-up, degrees | everything CARLA-side |

The handedness bridge is `(x, y, z) → (x, −y, z)` for positions and direction
vectors; rotations are transported by mapping the body's forward/right/up axes
and reassembling the CARLA rotator, which keeps the math transparent and
testable. Quaternions are `(w, x, y, z)`, active transforms, standard SE(3)
composition. One subtlety worth knowing: a CARLA actor's transform places its
*pivot*, but AlpaSim object poses give the *bounding-box center* — the
registry compensates per blueprint using `actor.bounding_box.location`.

### Why two Pythons

AlpaSim requires Python 3.12; the CARLA client wheel requires 3.10. Because
the boundary is gRPC, the bridge simply runs as its own 3.10 process. The only
thing installed into AlpaSim's environment is `alpasim-carla-configs` — pure
YAML registering an `alpasim.configs` entry point so `renderer=carla` works as
a wizard flag, wiring the runtime to the bridge's address via
`wizard.external_services.renderer`.

## Components

| Component | What it is |
|---|---|
| `src/alpasim_carla/server.py` | The gRPC server. Implements all 8 `SensorsimService` RPCs against a pluggable backend (CARLA or synthetic). |
| `src/alpasim_carla/world.py` | The CARLA backend: synchronous-mode connection, pooled RGB sensors, the render path (sync actors → place camera → tick → capture → encode). |
| `src/alpasim_carla/registry.py` | Track-id → CARLA actor registry, the bridge's only cross-call state. Unseen id → spawn, known id → teleport, absent id → despawn. Blueprint choice from the scene's actor table (label + bbox dims), with a box-prop fallback — objects are never dropped. |
| `src/alpasim_carla/frames.py` | Pure coordinate math between AlpaSim (right-handed ENU, quaternions) and Unreal (left-handed, degrees), including camera optical-frame handling. No CARLA or gRPC imports; fully unit-tested. |
| `src/alpasim_carla/cameras.py` | Maps `CameraSpec` intrinsics to CARLA's pinhole camera. Non-pinhole models (ftheta, fisheye, distortion, rolling shutter) fail explicitly unless `--allow-pinhole-approximation` is set. |
| `src/alpasim_carla/scenes.py` + `scenes/` | Scene manifests (YAML): `scene_id` → CARLA map, camera rig served by `get_available_cameras`, actor table, world anchor. `scenes/examples/` has ready-made scenes on stock towns. |
| `src/alpasim_carla/aslio.py` | Reader for AlpaSim `.asl` rollout logs (length-prefixed protobuf), used by the replay tools. |
| `src/alpasim_carla/_proto/`, `proto/` | The pinned AlpaSim protos (vendored, Apache-2.0, attribution in `proto/README.md`) and generated stubs. |
| `configs_pkg/` | `alpasim-carla-configs`: a pure-YAML package registering an `alpasim.configs` entry point, which makes `renderer=carla` a flag for AlpaSim's wizard. This is the only thing that touches AlpaSim's environment. |
| `tools/` | `replay_contract.py` (replay recorded traffic against the servicer, no CARLA), `replay_render.py` (same, real rendering + checks), `validate_rollout.py` (closed-loop run validation + video), `record_scene.py` (record CARLA drives into test fixtures), `gen_protos.sh`. |
| `docs/CONTRACT.md` | Per-RPC contract: every field consumed/produced, units, coordinate frames. PRs that change behavior must change it. |
| `evidence/` | Artifacts from the validation gates (G0–G4): replay reports, render metrics, closed-loop summaries, transcripts. |

## Install

```bash
# bridge (Python 3.10 env)
pip install "alpasim-carla[carla]"

# config shim (into AlpaSim's Python 3.12 env)
pip install alpasim-carla-configs        # or: pip install -e configs_pkg/
```

Custom CARLA builds: the PyPI `carla` wheel only speaks to stock 0.9.16. For
a custom server build, install the client wheel shipped inside its image:

```bash
CID=$(docker create <your-carla-image>) && \
  docker cp "$CID":/workspace/PythonAPI/carla/dist/. /tmp/carla-dist && \
  docker rm "$CID" && pip install /tmp/carla-dist/carla-0.9.16-cp310-cp310-linux_x86_64.whl
```

## Quickstart

1. Start a CARLA 0.9.16 server (or use one you already have):

   ```bash
   alpasim-carla launch-carla --image carlasim/carla:0.9.16 \
       --server-bin /home/carla/CarlaUE4.sh --gpu 0 --rpc-port 3000
   ```

2. Start the bridge:

   ```bash
   alpasim-carla serve --port 50051 --scenes-dir scenes/examples \
       --carla-host 127.0.0.1 --carla-port 3000 \
       --allow-pinhole-approximation
   ```

3. Run AlpaSim against it (from your AlpaSim checkout):

   ```bash
   uv run alpasim_wizard \
       --config-dir /path/to/alpasim-carla/configs_pkg/alpasim_carla_configs/configs \
       deploy=local topology=1gpu driver=alpamayo1_5 renderer=carla \
       'wizard.external_services.renderer=["<host-ip>:50051"]' \
       wizard.run_method=NONE wizard.log_dir=./out \
       runtime.endpoints.physics.skip=true \
       runtime.simulation_config.physics_update_mode=NONE \
       runtime.simulation_config.n_rollouts=1
   cd ./out && docker compose -f docker-compose.yaml \
       up --no-build --exit-code-from runtime-0 --remove-orphans
   ```

   `--config-dir` is optional if `alpasim-carla-configs` is installed in the
   wizard's env. `wizard.run_method=NONE` generates the compose file without
   running it; drop it to let the wizard launch compose itself.

The exact validated end-to-end commands and their artifacts are in `PLAN.md`
§4 and `evidence/`.

## Error policy

- Unknown `scene_id` → `NOT_FOUND`, listing available scenes.
- Unsupported camera model/distortion/shutter → `INVALID_ARGUMENT` naming the
  field; `--allow-pinhole-approximation` is the only degradation path, and it
  is opt-in.
- Unmappable object category → documented box-prop fallback plus a structured
  warning; never a silent skip.
- `render_lidar` → `UNIMPLEMENTED` (out of scope for v0.1).

## Scope and roadmap

v0.1: `render_rgb`, camera-only `render_aggregated`, all discovery RPCs,
pinhole cameras (+ explicit ftheta/fisheye approximation), example scenes on
stock towns, scene tooling, Docker.

Roadmap: lidar, distortion post-warp, rolling-shutter simulation, instance
pooling, CARLA-backed traffic/physics services, Windows.

## Development

```bash
pip install -e ".[dev]"          # carla not required for the test suite
pytest tests/ -m "not carla"     # simulator-free suite
tools/gen_protos.sh              # regenerate vendored stubs
```
