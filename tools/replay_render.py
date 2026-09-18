#!/usr/bin/env python
"""Gate G2: replay recorded render traffic against a REAL CARLA server.

Runs the bridge gRPC server in-process (real channel, same code path the
runtime uses) with the CarlaBackend attached to a live CARLA server, then
streams every recorded render_rgb request from a rollout.asl. Scripted
checks - none of this is eyeballed:

  C1  every response's image bytes decode, in the requested encoding;
  C2  decoded resolution == requested resolution_w/h;
  C3  after each request, bridge-managed actor count == len(dynamic_objects);
  C4  re-sending an identical request yields bridge-managed actor transforms
      identical within 1 cm / 0.1 deg (checked on the first and every Nth
      request);
  C5  p95 render_rgb latency recorded (reported, not thresholded).

Artifacts: metrics JSON + a contact sheet of evenly sampled frames.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import grpc
from PIL import Image

from alpasim_carla._proto.alpasim_grpc.v0 import sensorsim_pb2, sensorsim_pb2_grpc
from alpasim_carla.aslio import read_sensorsim_log
from alpasim_carla.catalog import default_catalog, load_catalog
from alpasim_carla.registry import audit_scene_blueprints
from alpasim_carla.scenes import manifest_from_asl
from alpasim_carla.server import ServerOptions, build_server

_PIL_FORMAT = {
    sensorsim_pb2.ImageFormat.PNG: "PNG",
    sensorsim_pb2.ImageFormat.JPEG: "JPEG",
}


def transforms_close(a, b, pos_tol_m=0.01, ang_tol_deg=0.1):
    """Compare registry transform snapshots; returns (ok, max_pos_m, max_ang_deg)."""
    if set(a) != set(b):
        return False, math.inf, math.inf
    max_pos = 0.0
    max_ang = 0.0
    for track_id in a:
        (loc_a, rot_a), (loc_b, rot_b) = a[track_id], b[track_id]
        for da, db in zip(loc_a, loc_b):
            max_pos = max(max_pos, abs(da - db))
        for da, db in zip(rot_a, rot_b):
            delta = abs(da - db) % 360.0
            max_ang = max(max_ang, min(delta, 360.0 - delta))
    return (max_pos <= pos_tol_m and max_ang <= ang_tol_deg), max_pos, max_ang


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asl", required=True)
    parser.add_argument("--carla-host", default="127.0.0.1")
    parser.add_argument("--carla-port", type=int, required=True)
    parser.add_argument("--carla-map", default="Town10HD_Opt")
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--contact-sheet", required=True)
    parser.add_argument("--max-requests", type=int, default=0, help="0 = all")
    parser.add_argument("--repeat-check-every", type=int, default=50)
    parser.add_argument("--allow-pinhole-approximation", action="store_true")
    parser.add_argument(
        "--blueprint-catalog",
        help="blueprint listing from tools/list_blueprints.py; required - "
        "there is no built-in table, the curated 0.9.16 one having been "
        "wrong in every row on 0.10",
    )
    parser.add_argument(
        "--expect-carla-version",
        default="",
        help="override the carla_version declared by the scene manifest",
    )
    parser.add_argument("--anchor", type=float, nargs=3, default=(0.0, 0.0, 0.0))
    args = parser.parse_args()

    from alpasim_carla.world import CarlaBackend  # needs the carla wheel

    log = read_sensorsim_log(args.asl)
    manifest = manifest_from_asl(
        args.asl, carla_map=args.carla_map, anchor_translation=tuple(args.anchor)
    )
    options = ServerOptions(allow_pinhole_approximation=args.allow_pinhole_approximation)
    catalog = load_catalog(args.blueprint_catalog) if args.blueprint_catalog else default_catalog()
    backend = CarlaBackend(
        host=args.carla_host,
        port=args.carla_port,
        options=options,
        expect_version=args.expect_carla_version or manifest.carla_version,
        catalog=catalog,
    )
    # Gate G2: resolve every gated actor through the ladder BEFORE the
    # rollout. A boxed car, pedestrian or cyclist is visible to the driver,
    # so the run's policy score would be meaningless.
    fallback_actors = audit_scene_blueprints(manifest, catalog)
    server, port = build_server(
        {manifest.scene_id: manifest}, backend, options, port=0, host="127.0.0.1"
    )
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = sensorsim_pb2_grpc.SensorsimServiceStub(channel)

    requests = log.render_requests
    if args.max_requests:
        requests = requests[: args.max_requests]

    metrics = {
        "tool": "replay_render",
        "asl": args.asl,
        "scene_id": manifest.scene_id,
        "carla_map": args.carla_map,
        "total_requests": len(requests),
        "checks": {"decode": 0, "resolution": 0, "actor_count": 0, "repeat": 0},
        "blueprint_catalog": catalog.source,
        "fallback_actors": fallback_actors,
        "failures": [],
        "per_camera": {},
        "approximation": args.allow_pinhole_approximation,
    }
    failures = metrics["failures"]
    if fallback_actors:
        failures.append(
            "blueprint_fallback: gated actors would render as "
            f"{catalog.fallback_prop}: {fallback_actors}. Regenerate the "
            "listing with tools/list_blueprints.py, or filter these actors "
            "out of the scene package."
        )
    latencies = []
    samples = []
    sample_every = max(1, len(requests) // 16)

    try:
        for i, original in enumerate(requests):
            request = sensorsim_pb2.RGBRenderRequest()
            request.CopyFrom(original)
            if request.insert_ego_mask:
                request.insert_ego_mask = False
                request.ClearField("ego_mask_id")

            start = time.perf_counter()
            try:
                response = stub.render_rgb(request, timeout=180)
            except grpc.RpcError as exc:
                failures.append(f"render_rgb[{i}] {exc.code().name}: {exc.details()}")
                continue
            latencies.append(time.perf_counter() - start)

            cam = request.camera_intrinsics.logical_id or "?"
            metrics["per_camera"][cam] = metrics["per_camera"].get(cam, 0) + 1

            # C1 + C2
            try:
                image = Image.open(io.BytesIO(response.image_bytes))
                image.load()
                metrics["checks"]["decode"] += 1
            except Exception as exc:  # noqa: BLE001
                failures.append(f"render_rgb[{i}] decode failed: {exc}")
                continue
            expected_format = _PIL_FORMAT.get(request.image_format)
            if expected_format and image.format != expected_format:
                failures.append(
                    f"render_rgb[{i}] format {image.format} != {expected_format}"
                )
            if image.size != (request.resolution_w, request.resolution_h):
                failures.append(
                    f"render_rgb[{i}] size {image.size} != "
                    f"({request.resolution_w},{request.resolution_h})"
                )
            else:
                metrics["checks"]["resolution"] += 1

            # C3: bridge-managed actor parity
            count = backend.registry.actor_count if backend.registry else -1
            if count != len(request.dynamic_objects):
                failures.append(
                    f"render_rgb[{i}] managed actors {count} != "
                    f"{len(request.dynamic_objects)} dynamic_objects"
                )
            else:
                metrics["checks"]["actor_count"] += 1

            # C4: determinism on identical re-send
            if i == 0 or (args.repeat_check_every and i % args.repeat_check_every == 0):
                snapshot_a = backend.registry.transforms()
                stub.render_rgb(request, timeout=180)
                snapshot_b = backend.registry.transforms()
                ok, max_pos, max_ang = transforms_close(snapshot_a, snapshot_b)
                metrics.setdefault("repeat_deltas", []).append(
                    {"i": i, "max_pos_m": max_pos, "max_ang_deg": max_ang}
                )
                if ok:
                    metrics["checks"]["repeat"] += 1
                else:
                    failures.append(
                        f"render_rgb[{i}] repeat divergence pos={max_pos:.4f}m "
                        f"ang={max_ang:.4f}deg"
                    )

            if i % sample_every == 0 and len(samples) < 16:
                samples.append((i, cam, image.copy()))
            if i % 100 == 0:
                print(f"  [{i}/{len(requests)}] p50 so far: "
                      f"{sorted(latencies)[len(latencies)//2]*1000:.0f}ms", flush=True)
    finally:
        server.stop(grace=None)
        backend.close()

    latencies.sort()
    if latencies:
        metrics["latency_ms"] = {
            "p50": round(latencies[len(latencies) // 2] * 1000, 1),
            "p95": round(latencies[int(len(latencies) * 0.95)] * 1000, 1),
            "mean": round(sum(latencies) / len(latencies) * 1000, 1),
            "count": len(latencies),
        }
    metrics["passed"] = not failures

    # Contact sheet: 4x4 grid of sampled frames.
    if samples:
        thumb_w, thumb_h = 480, 270
        cols = 4
        rows = math.ceil(len(samples) / cols)
        sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (20, 20, 20))
        for n, (i, cam, image) in enumerate(samples):
            thumb = image.resize((thumb_w, thumb_h))
            sheet.paste(thumb, ((n % cols) * thumb_w, (n // cols) * thumb_h))
        Path(args.contact_sheet).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.contact_sheet, "JPEG", quality=85)
        metrics["contact_sheet"] = args.contact_sheet

    Path(args.metrics).parent.mkdir(parents=True, exist_ok=True)
    with open(args.metrics, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"replay_render: {'PASS' if metrics['passed'] else 'FAIL'} -> {args.metrics}")
    if failures:
        print("\n".join(failures[:20]))
    return 0 if metrics["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
