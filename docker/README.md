# Docker

Two containers, by design (CARLA server and bridge stay independent):

```bash
# 1. CARLA server (official image; any reachable CARLA 0.9.16 works)
docker run -d --name carla --gpus device=0 -p 2000-2002:2000-2002 \
  carlasim/carla:0.9.16 /home/carla/CarlaUE4.sh -RenderOffScreen -carla-server \
  -nosound -stdout -FullStdOutLogOutput -carla-rpc-port=2000

# 2. The bridge
docker build -f docker/Dockerfile -t alpasim-carla .
docker run -d --name alpasim-carla --network host alpasim-carla \
  serve --port 50051 --scenes-dir scenes/examples \
  --carla-host 127.0.0.1 --carla-port 2000
```

The launch flags above mirror the pattern used in production by SimForge's
CARLA workers (GPU pinning via `--gpus device=N`; add
`-ini:[/Script/Engine.RendererSettings]:r.GraphicsAdapter=<idx>` when more
than one GPU is visible inside the container).
