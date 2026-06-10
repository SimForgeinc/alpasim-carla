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

AlpaSim's runtime owns all world state. Each tick it sends the renderer a
`render_rgb` request containing the pose of every object (`dynamic_objects`),
the camera pose and intrinsics, and a time window. The bridge teleports CARLA
actors to exactly those poses (physics and autopilot off), places the camera,
ticks the simulator once, captures the frame, and returns encoded image bytes.
CARLA never simulates motion — it only renders the state AlpaSim dictates.

```
AlpaSim runtime ──render_rgb──▶ alpasim-carla ──tick/capture──▶ CARLA server
      ▲                              (3.10 process)              (any reachable
      └── frames ── driver policy                                 0.9.16 server)
```

The two-Python split is structural: AlpaSim requires 3.12, the CARLA client
wheel requires 3.10. The gRPC boundary means the bridge just runs as its own
3.10 process.

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
