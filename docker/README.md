# Docker

Two containers, by design (CARLA server and bridge stay independent):

```bash
# 1. CARLA server (official image; any reachable CARLA 0.9.16 works)
docker run -d --name carla --gpus device=0 -p 2000-2002:2000-2002 \
  carlasim/carla:0.9.16 /home/carla/CarlaUE4.sh -RenderOffScreen -carla-server \
  -nosound -stdout -FullStdOutLogOutput -carla-rpc-port=2000

# 2. The bridge - CARLA_IMAGE has no default: the build copies the client
#    wheel out of the server image, so it must name the image by digest.
docker build -f docker/Dockerfile \
  --build-arg CARLA_IMAGE=carlasim/carla@sha256:<digest> \
  --build-arg CARLA_PYTHONAPI=/workspace/PythonAPI \
  -t alpasim-carla .
docker run -d --name alpasim-carla --network host alpasim-carla \
  serve --port 50051 --scenes-dir scenes/examples \
  --carla-host 127.0.0.1 --carla-port 2000
```

## Python version is decided by the image, not by preference

`PYTHON_VERSION` defaults to **3.10**. That is a pin: the Belmont 0.10 image
(`ghcr.io/simforgeinc/carla-rfs-munich-belmont@sha256:d1b16b06...`) ships
exactly one client wheel, `carla-0.10.0-cp310-cp310-linux_x86_64.whl`, so a
3.12 base image cannot install the client it just copied. Stock 0.9.16 ships
cp310-cp312, so 3.10 serves both and needs no override. The 0.10 build
measured against that digest is `alpasim-carla:0.10.0-belmont`,
`sha256:1b7cec38...`, 403 MB, python 3.10.21.

If a future image ships different wheels, the wheel-selection step prints
every wheel it found; pass `--build-arg PYTHON_VERSION=<one of them>`.

## The Belmont 0.10 line

```bash
docker build -f docker/Dockerfile \
  --build-arg CARLA_IMAGE=ghcr.io/simforgeinc/carla-rfs-munich-belmont@sha256:d1b16b061ef1c2947caf2d87109d2809617d5ebfd8c3cb999637e8751da83d22 \
  -t alpasim-carla:0.10.0-belmont .
```

The 0.10 PythonAPI root (`/home/carla/PythonAPI`) is the Dockerfile's
default, so only `CARLA_IMAGE` is needed here.

The launch flags above mirror the pattern used in production by SimForge's
CARLA workers (GPU pinning via `--gpus device=N`; add
`-ini:[/Script/Engine.RendererSettings]:r.GraphicsAdapter=<idx>` when more
than one GPU is visible inside the container).
