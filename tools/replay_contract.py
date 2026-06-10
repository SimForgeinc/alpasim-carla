#!/usr/bin/env python
"""Gate G0: replay every recorded sensorsim request against the bridge.

Streams the full sensorsim request traffic from one or more real rollout.asl
logs to a SensorsimService endpoint (by default an in-process server with the
synthetic backend, scene-seeded from the same log) and validates responses
the way AlpaSim's runtime would:

  * startup probes mirroring alpasim_runtime.validation: get_version (and the
    grpc_api_version it reports), get_available_scenes (the rollout's scene
    must be listed, or "*"),
  * get_available_cameras must cover every camera logical_id that appears in
    the recorded render requests (the runtime treats the renderer as the
    source of truth for cameras - local config can only modify, not add),
  * every recorded render_rgb request must be answered OK with image bytes
    that decode to exactly resolution_w x resolution_h in the requested
    encoding (request acceptance matching adapted from
    alpasim_runtime.replay_services.asl_reader, which tolerates float drift -
    we go further and replay the recorded bytes verbatim, so acceptance is
    exact),
  * the remaining RPCs (render_aggregated, render_lidar,
    get_available_trajectories, get_available_ego_masks) are exercised with
    synthetic calls so all 8 RPCs answer - 0 UNIMPLEMENTED errors.

Writes a JSON report (per-RPC request counts, pass/fail per message, failure
details) and exits nonzero on any failure.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

# Allow running from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import grpc
from PIL import Image

from alpasim_carla import GRPC_API_VERSION
from alpasim_carla._proto.alpasim_grpc.v0 import (
    common_pb2,
    sensorsim_pb2,
    sensorsim_pb2_grpc,
)
from alpasim_carla.aslio import read_sensorsim_log
from alpasim_carla.scenes import manifest_from_asl
from alpasim_carla.server import ServerOptions, SyntheticBackend, build_server

_PIL_FORMAT = {
    sensorsim_pb2.ImageFormat.PNG: "PNG",
    sensorsim_pb2.ImageFormat.JPEG: "JPEG",
}


def validate_rgb_response(
    request: sensorsim_pb2.RGBRenderRequest, response: sensorsim_pb2.RGBRenderReturn
) -> list[str]:
    problems = []
    if not response.image_bytes:
        problems.append("empty image_bytes")
        return problems
    try:
        image = Image.open(io.BytesIO(response.image_bytes))
        image.load()
    except Exception as exc:  # noqa: BLE001
        problems.append(f"image bytes do not decode: {exc}")
        return problems
    if image.size != (request.resolution_w, request.resolution_h):
        problems.append(
            f"decoded size {image.size} != requested "
            f"({request.resolution_w}, {request.resolution_h})"
        )
    expected_format = _PIL_FORMAT.get(request.image_format)
    if expected_format and image.format != expected_format:
        problems.append(f"decoded format {image.format} != requested {expected_format}")
    return problems


def replay_one(asl_path: str, stub, report: dict) -> bool:
    log = read_sensorsim_log(asl_path)
    scene_id = log.scene_id
    entry = {
        "asl": asl_path,
        "scene_id": scene_id,
        "entry_counts": log.entry_counts,
        "rpcs": {},
        "failures": [],
    }
    report["rollouts"].append(entry)
    ok = True

    def fail(msg: str) -> None:
        nonlocal ok
        ok = False
        entry["failures"].append(msg)

    # --- startup probes (mirrors alpasim_runtime.validation) ---------------
    version = stub.get_version(common_pb2.Empty(), timeout=10)
    entry["rpcs"]["get_version"] = {"count": 1, "version_id": version.version_id}
    got = (
        version.grpc_api_version.major,
        version.grpc_api_version.minor,
        version.grpc_api_version.patch,
    )
    if got != GRPC_API_VERSION:
        fail(f"get_version grpc_api_version {got} != pinned {GRPC_API_VERSION}")

    scenes = stub.get_available_scenes(common_pb2.Empty(), timeout=10)
    entry["rpcs"]["get_available_scenes"] = {"count": 1, "scene_ids": list(scenes.scene_ids)}
    if scene_id not in scenes.scene_ids and "*" not in scenes.scene_ids:
        fail(f"scene {scene_id} not in get_available_scenes {list(scenes.scene_ids)}")

    # --- get_available_cameras must cover the requested rig ----------------
    cameras = stub.get_available_cameras(
        sensorsim_pb2.AvailableCamerasRequest(scene_id=scene_id), timeout=10
    )
    served_ids = {c.logical_id for c in cameras.available_cameras}
    requested_ids = {r.camera_intrinsics.logical_id for r in log.render_requests}
    entry["rpcs"]["get_available_cameras"] = {
        "count": 1,
        "served": sorted(served_ids),
        "needed": sorted(requested_ids),
    }
    missing = requested_ids - served_ids
    if missing:
        fail(
            f"get_available_cameras is missing {sorted(missing)}; the runtime "
            "cannot add cameras locally (camera_catalog merge only modifies)"
        )

    masks = stub.get_available_ego_masks(common_pb2.Empty(), timeout=10)
    entry["rpcs"]["get_available_ego_masks"] = {
        "count": 1,
        "served_masks": len(masks.ego_mask_metadata),
        "recorded_masks": (
            len(log.available_ego_masks_return.ego_mask_metadata)
            if log.available_ego_masks_return
            else 0
        ),
        "note": "bridge publishes no ego masks in v0.1; runtime then disables ego masking",
    }

    trajectories = stub.get_available_trajectories(
        sensorsim_pb2.AvailableTrajectoriesRequest(scene_id=scene_id), timeout=10
    )
    entry["rpcs"]["get_available_trajectories"] = {
        "count": 1,
        "trajectories": len(trajectories.available_trajectories),
    }

    # --- replay every recorded render request ------------------------------
    render_failures = 0
    latencies = []
    for i, request in enumerate(log.render_requests):
        # The runtime would never send insert_ego_mask=true to a renderer
        # publishing no masks; recorded NuRec traffic may have it for masks we
        # do not serve. Clear it exactly the way a runtime pointed at this
        # bridge would (determine_ego_mask_id -> None).
        replayed = sensorsim_pb2.RGBRenderRequest()
        replayed.CopyFrom(request)
        if replayed.insert_ego_mask:
            replayed.insert_ego_mask = False
            replayed.ClearField("ego_mask_id")
        start = time.perf_counter()
        try:
            response = stub.render_rgb(replayed, timeout=60)
        except grpc.RpcError as exc:
            render_failures += 1
            fail(f"render_rgb[{i}] {exc.code().name}: {exc.details()}")
            continue
        latencies.append(time.perf_counter() - start)
        problems = validate_rgb_response(replayed, response)
        if problems:
            render_failures += 1
            fail(f"render_rgb[{i}]: {'; '.join(problems)}")
    latencies.sort()
    entry["rpcs"]["render_rgb"] = {
        "count": len(log.render_requests),
        "failed": render_failures,
        "p50_ms": round(latencies[len(latencies) // 2] * 1000, 2) if latencies else None,
        "p95_ms": round(latencies[int(len(latencies) * 0.95)] * 1000, 2)
        if latencies
        else None,
    }

    # --- exercise the remaining RPCs synthetically --------------------------
    if log.render_requests:
        agg = sensorsim_pb2.AggregatedRenderRequest()
        for request in log.render_requests[:2]:
            replayed = agg.rgb_requests.add()
            replayed.CopyFrom(request)
            if replayed.insert_ego_mask:
                replayed.insert_ego_mask = False
                replayed.ClearField("ego_mask_id")
        agg_ret = stub.render_aggregated(agg, timeout=60)
        entry["rpcs"]["render_aggregated"] = {
            "count": 1,
            "rgb_returns": len(agg_ret.rgb_returns),
        }
        if len(agg_ret.rgb_returns) != len(agg.rgb_requests):
            fail(
                f"render_aggregated returned {len(agg_ret.rgb_returns)} rgb_returns "
                f"for {len(agg.rgb_requests)} requests"
            )

    lidar_request = sensorsim_pb2.LidarRenderRequest(scene_id=scene_id)
    try:
        lidar = stub.render_lidar(lidar_request, timeout=10)
        entry["rpcs"]["render_lidar"] = {"count": 1, "num_points": lidar.num_points}
    except grpc.RpcError as exc:
        entry["rpcs"]["render_lidar"] = {"count": 1, "error": exc.code().name}
        fail(f"render_lidar: {exc.code().name}: {exc.details()}")

    entry["passed"] = ok
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asl", action="append", required=True, help="rollout.asl path (repeatable)")
    parser.add_argument("--report", required=True, help="output JSON report path")
    parser.add_argument(
        "--target",
        help="address of an already-running bridge; default: in-process synthetic server",
    )
    args = parser.parse_args()

    report = {
        "tool": "replay_contract",
        "pinned_api_version": list(GRPC_API_VERSION),
        "rollouts": [],
    }

    server = None
    if args.target:
        target = args.target
    else:
        scenes = {}
        for asl in args.asl:
            manifest = manifest_from_asl(asl)
            scenes[manifest.scene_id] = manifest
        server, port = build_server(
            scenes, SyntheticBackend(), ServerOptions(), port=0, host="127.0.0.1"
        )
        server.start()
        target = f"127.0.0.1:{port}"

    try:
        channel = grpc.insecure_channel(target)
        stub = sensorsim_pb2_grpc.SensorsimServiceStub(channel)
        results = [replay_one(asl, stub, report) for asl in args.asl]
        all_ok = all(results)
    finally:
        if server is not None:
            server.stop(grace=None)

    report["passed"] = all_ok
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)
    print(f"replay_contract: {'PASS' if all_ok else 'FAIL'} -> {args.report}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
