"""Command-line interface: `alpasim-carla <subcommand>`.

Subcommands:
  serve           - run the SensorsimService bridge (synthetic or CARLA backend)
  scene-from-asl  - generate a scene manifest YAML from a recorded rollout.asl
  launch-carla    - print/exec the docker command for a CARLA server, using the
                    same launch pattern proven by SimForge's production CARLA
                    workers (-RenderOffScreen, -nosound, explicit rpc port,
                    GraphicsAdapter pinning for GPU selection)
"""

from __future__ import annotations

import argparse
import logging
import shlex
import subprocess
import sys
import time

from alpasim_carla import __version__
from alpasim_carla.scenes import load_scene_dir, manifest_from_asl, manifest_to_yaml
from alpasim_carla.server import ServerOptions, SyntheticBackend, build_server

logger = logging.getLogger("alpasim_carla.cli")

DEFAULT_CARLA_IMAGE = "carlasim/carla:0.9.16"


def _git_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def cmd_serve(args: argparse.Namespace) -> int:
    scenes = load_scene_dir(args.scenes_dir) if args.scenes_dir else {}
    for asl in args.scene_from_asl or []:
        manifest = manifest_from_asl(asl, carla_map=args.carla_map)
        scenes[manifest.scene_id] = manifest
        logger.info("Loaded scene %s from %s", manifest.scene_id, asl)
    if not scenes:
        print(
            "No scenes configured. Pass --scenes-dir and/or --scene-from-asl.",
            file=sys.stderr,
        )
        return 2

    options = ServerOptions(
        allow_pinhole_approximation=args.allow_pinhole_approximation,
        git_hash=_git_hash(),
    )
    if args.backend == "synthetic":
        backend = SyntheticBackend()
    else:
        from alpasim_carla.world import CarlaBackend  # imports `carla` lazily

        backend = CarlaBackend(
            host=args.carla_host,
            port=args.carla_port,
            options=options,
            fixed_delta_seconds=args.fixed_delta_seconds,
        )

    server, port = build_server(scenes, backend, options, port=args.port)
    server.start()
    logger.info(
        "alpasim-carla %s serving SensorsimService on :%d (backend=%s, scenes=%s)",
        __version__,
        port,
        backend.name,
        sorted(scenes),
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.stop(grace=5)
        backend.close()
    return 0


def cmd_scene_from_asl(args: argparse.Namespace) -> int:
    manifest = manifest_from_asl(
        args.asl,
        carla_map=args.carla_map,
        anchor_translation=tuple(args.anchor or (0.0, 0.0, 0.0)),
        anchor_yaw_deg=args.anchor_yaw,
    )
    text = manifest_to_yaml(manifest)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"Wrote {args.out} (scene_id={manifest.scene_id})")
    else:
        print(text)
    return 0


def cmd_launch_carla(args: argparse.Namespace) -> int:
    name = args.name or f"alpasim-carla-server-{args.rpc_port}"
    cmd = [
        "docker", "run", "--rm", "-d",
        "--name", name,
        "--gpus", f"device={args.gpu}",
        "-p", f"{args.rpc_port}-{args.rpc_port + 2}:{args.rpc_port}-{args.rpc_port + 2}",
        "-e", "SDL_AUDIODRIVER=dummy",
        args.image,
        args.server_bin,
        "-RenderOffScreen",
        "-carla-server",
        "-nosound",
        "-stdout",
        "-FullStdOutLogOutput",
        f"-carla-rpc-port={args.rpc_port}",
    ]
    if args.quality:
        cmd.append(f"-quality-level={args.quality}")
    print(shlex.join(cmd))
    if args.dry_run:
        return 0
    return subprocess.run(cmd).returncode


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(prog="alpasim-carla")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the SensorsimService bridge")
    serve.add_argument("--port", type=int, default=50051)
    serve.add_argument("--scenes-dir", help="directory of scene manifest YAMLs")
    serve.add_argument(
        "--scene-from-asl",
        action="append",
        help="generate a scene directly from a rollout.asl (repeatable)",
    )
    serve.add_argument("--backend", choices=["carla", "synthetic"], default="carla")
    serve.add_argument("--carla-host", default="127.0.0.1")
    serve.add_argument("--carla-port", type=int, default=2000)
    serve.add_argument("--carla-map", default="Town10HD_Opt",
                       help="map used for --scene-from-asl scenes")
    serve.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    serve.add_argument(
        "--allow-pinhole-approximation",
        action="store_true",
        help="explicitly allow rendering non-pinhole camera specs (ftheta, "
        "fisheye, distortion, rolling shutter) as an ideal pinhole",
    )
    serve.set_defaults(func=cmd_serve)

    sfa = sub.add_parser("scene-from-asl", help="generate a scene manifest from a rollout log")
    sfa.add_argument("asl")
    sfa.add_argument("--out")
    sfa.add_argument("--carla-map", default="Town10HD_Opt")
    sfa.add_argument("--anchor", type=float, nargs=3, metavar=("X", "Y", "Z"))
    sfa.add_argument("--anchor-yaw", type=float, default=0.0)
    sfa.set_defaults(func=cmd_scene_from_asl)

    lc = sub.add_parser("launch-carla", help="launch a CARLA server container")
    lc.add_argument("--image", default=DEFAULT_CARLA_IMAGE)
    lc.add_argument("--server-bin", default="/workspace/CarlaUE4.sh",
                    help="CarlaUE4.sh path inside the image (stock carlasim "
                    "image uses /home/carla/CarlaUE4.sh)")
    lc.add_argument("--gpu", type=int, default=0)
    lc.add_argument("--rpc-port", type=int, default=2000)
    lc.add_argument("--quality", default="Epic")
    lc.add_argument("--name")
    lc.add_argument("--dry-run", action="store_true")
    lc.set_defaults(func=cmd_launch_carla)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
