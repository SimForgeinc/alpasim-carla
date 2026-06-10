# alpasim-carla

**An open-source CARLA renderer for NVIDIA AlpaSim.** Point this bridge at
your CARLA server, point AlpaSim's config at the bridge, and any AlpaSim
driver policy (Alpamayo 1.5, Transfuser, your own) drives closed-loop inside
CARLA worlds — with AlpaSim's runtime, controller, physics, and scorers
unchanged.

Pinned and tested against: AlpaSim commit
`a1f05bb628f3d1d19d79d44188e836e9108f98c6` (proto v0, `alpasim_grpc` 0.54.0)
· CARLA **0.9.16** · bridge Python **3.10.x** · NVIDIA A100, driver 5xx,
CARLA in docker with `-RenderOffScreen`. License: Apache-2.0 (matching
AlpaSim; its protos are vendored under `proto/` with attribution).

---

## What is this, if I know neither protobuf nor AlpaSim?

**Protobuf/gRPC in one paragraph.** A `.proto` file declares typed messages
and services (named remote calls with request/response types). `protoc`
turns it into Python classes that serialize to a compact wire format, and
gRPC exposes the service over the network so a client in one process can
call a server in another — even across Python versions or languages. The
`.proto` files are the whole contract: both sides only need to agree on
them. AlpaSim publishes a renderer contract called `SensorsimService`; this
library is a server that fulfills it using CARLA.

**AlpaSim's closed loop.** AlpaSim's *runtime* owns all world state. Each
tick:

```
        ┌──────────────────────────────────────────────────────┐
        │                   AlpaSim RUNTIME                    │
        │     (owns all object/ego trajectories and time)      │
        └──┬─────────────────┬─────────────────────┬───────────┘
 "objects are HERE,          │                     │
  camera is HERE —   "here are frames,    "apply this plan →
  give me frames"     give me a plan"      new ego pose"
           │                 │                     │
           ▼                 ▼                     ▼
    ┌────────────┐    ┌────────────┐   ┌─────────────────────┐
    │  RENDERER  │    │   DRIVER   │   │ CONTROLLER/PHYSICS  │
    │ (this lib) │    │ (Alpamayo…)│   │   (vehicle model)   │
    └────────────┘    └────────────┘   └─────────────────────┘
           └───────────── repeat every tick ───────────┘
```

**The puppet theater.** AlpaSim moves the puppets; CARLA takes the photo.
On every `render_rgb` the request says where every object is and where the
camera is. The bridge teleports CARLA actors to exactly those poses (CARLA
physics and autopilot OFF), places the camera, ticks once, captures, and
returns encoded image bytes. CARLA never simulates object motion — two
owners of state would diverge. The bridge's only cross-call memory is the
track-id registry: unseen id → spawn, known id → teleport, absent id →
despawn.

**Why two Pythons.** AlpaSim needs Python 3.12; CARLA's client wheel needs
3.10. The gRPC boundary means the bridge is simply its own 3.10 process —
you never fight that conflict. The only thing installed into AlpaSim's env
is `alpasim-carla-configs` (pure YAML), which makes `renderer=carla` a
wizard flag.

---

## Install

```bash
# the bridge (Python 3.10)
pip install "alpasim-carla[carla]"        # or: pip install -e ".[carla,dev]"

# the wizard config shim (into AlpaSim's Python 3.12 env)
pip install alpasim-carla-configs        # or: pip install -e configs_pkg/
```

> **Custom CARLA builds:** the PyPI `carla` wheel only speaks to stock
> CARLA 0.9.16. If your server is a custom build (e.g. an all-maps CI image),
> install the client wheel that ships inside it instead — it lives at
> `/workspace/PythonAPI/carla/dist/*cp310*linux_x86_64.whl` in CARLA images:
>
> ```bash
> CID=$(docker create <your-carla-image>) && \
>   docker cp "$CID":/workspace/PythonAPI/carla/dist/. /tmp/carla-dist && \
>   docker rm "$CID" && pip install /tmp/carla-dist/carla-0.9.16-cp310-cp310-linux_x86_64.whl
> ```

## Quickstart

1. **Start a CARLA 0.9.16 server** (bring your own, or):

   ```bash
   alpasim-carla launch-carla --image carlasim/carla:0.9.16 \
       --server-bin /home/carla/CarlaUE4.sh --gpu 0 --rpc-port 3000
   ```

2. **Start the bridge** (Python 3.10 env):

   ```bash
   alpasim-carla serve --port 50051 --scenes-dir scenes/examples \
       --carla-host 127.0.0.1 --carla-port 3000 \
       --allow-pinhole-approximation
   ```

3. **Run AlpaSim against it** (AlpaSim checkout, Python 3.12 env with
   `alpasim-carla-configs` installed):

   ```bash
   uv run alpasim_wizard deploy=local topology=1gpu driver=alpamayo1 \
       renderer=carla 'wizard.external_services.renderer=["127.0.0.1:50051"]' \
       runtime.endpoints.physics.skip=true \
       runtime.simulation_config.physics_update_mode=NONE \
       wizard.log_dir=./out
   ```

The exact end-to-end commands used to validate this repo (with artifacts)
live in `PLAN.md` §4 and `evidence/`.

## The contract, scenes, and the no-guessing policy

* `docs/CONTRACT.md` documents, per RPC, every field consumed/produced with
  units and coordinate frames. PRs that change behavior must change it.
* Scene manifests (`scenes/`) map an AlpaSim `scene_id` to a CARLA map, the
  camera rig served by `get_available_cameras`, an actor table (labels +
  bbox dims → blueprints), and a `local_to_world` anchor. Generate one from
  a recorded rollout: `alpasim-carla scene-from-asl rollout.asl --out my.yaml`.
* No silent fallbacks: unsupported camera models fail with a gRPC error
  naming the field; `--allow-pinhole-approximation` is the only (explicit)
  degradation path. Unknown scenes fail listing the available ones.
  Unmappable object categories spawn a documented box-prop fallback and log
  a structured warning — never a silent skip.

## Scope (v0.1) and roadmap

In: `render_rgb`, camera-only `render_aggregated`, all discovery RPCs,
pinhole cameras (+ explicit ftheta/fisheye approximation), example scenes on
stock towns, scene-from-asl tooling, Docker.
Roadmap: lidar, distortion post-warp, rolling-shutter simulation, instance
pooling, CARLA-backed traffic/physics services, Windows.

## Development

```bash
pip install -e ".[dev]"          # no carla needed for the test suite
pytest tests/ -m "not carla"     # simulator-free suite (gate G1)
tools/gen_protos.sh              # regenerate vendored stubs
```
