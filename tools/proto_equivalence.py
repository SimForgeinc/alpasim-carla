#!/usr/bin/env python
"""Prove the sensorsim wire seam survives the alpasim_grpc 0.54.0 -> 0.55.0 bump.

The vendored protos are pinned at AlpaSim commit a1f05bb628f3
(``alpasim_grpc`` 0.54.0). Upstream is at 0.55.0, which adds
``batch_render_rgb`` and ``get_loaded_scenes`` to sensorsim.proto plus fields
to logging.proto and runtime.proto, and which *removes* an RPC and renames a
field in traffic.proto.

Only the sensorsim and logging seam matters to this bridge, and only for the
fields both versions share. This tool encodes a corpus of representative
messages under each generation and compares the bytes: if they are identical,
a 0.55.0 client and a 0.54.0 server agree on the wire, and the bump cannot
break rendering.

Both generations declare the same proto package (``nre.grpc.protos.sensorsim``),
so they cannot be imported into one interpreter - protobuf's global descriptor
pool rejects the second registration. Each side therefore encodes in its own
subprocess and only hex digests cross the boundary.

What this does NOT cover, by construction: the corpus contains only messages
this bridge touches, so ``controller.proto`` (``VDCService``) and
``traffic.proto`` are never encoded. traffic.proto in particular is known to
have changed incompatibly - 0.55.0 removes the ``get_available_scenes`` RPC
and the ``supported_map_ids`` field, and renames ``map_id`` to ``scene_id``.
A PASS here means "the sensorsim and logging seams are unaffected", not "the
bump is safe everywhere". Whoever writes traffic-scripted must re-check
traffic.proto against 0.55.0 directly.

Usage:

    python tools/proto_equivalence.py \\
        --upstream /path/to/alpasim/src/grpc/alpasim_grpc/v0

Exit code 0 means every shared message encodes identically.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent

# The corpus. Each entry names a message and the field values to set. Values
# are chosen to exercise every field the bridge reads or writes on the render
# path, including nested messages, repeated fields and enums - a field whose
# number or type moved between generations produces different bytes here.
CORPUS_SOURCE = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from alpasim_grpc.v0 import common_pb2, sensorsim_pb2, logging_pb2

out = {}

def pose(x, y, z, w=1.0):
    p = common_pb2.Pose()
    p.vec.x, p.vec.y, p.vec.z = x, y, z
    p.quat.w, p.quat.x, p.quat.y, p.quat.z = w, 0.1, 0.2, 0.3
    return p

spec = sensorsim_pb2.CameraSpec()
spec.logical_id = "camera_front_wide_120fov"
spec.resolution_w, spec.resolution_h = 1920, 1080
spec.shutter_type = sensorsim_pb2.ShutterType.ROLLING_TOP_TO_BOTTOM
spec.opencv_pinhole_param.principal_point_x = 960.5
spec.opencv_pinhole_param.principal_point_y = 540.25
spec.opencv_pinhole_param.focal_length_x = 1234.5
spec.opencv_pinhole_param.focal_length_y = 1234.5
spec.opencv_pinhole_param.radial_coeffs.extend([0.1, -0.2, 0.3])
spec.opencv_pinhole_param.tangential_coeffs.extend([0.01, -0.02])
out["CameraSpec/pinhole"] = spec.SerializeToString()

ftheta = sensorsim_pb2.CameraSpec()
ftheta.logical_id = "camera_cross_left_120fov"
ftheta.resolution_w, ftheta.resolution_h = 1920, 1080
ftheta.ftheta_param.principal_point_x = 959.0
ftheta.ftheta_param.principal_point_y = 543.0
ftheta.ftheta_param.reference_poly = (
    sensorsim_pb2.FthetaCameraParam.PolynomialType.PIXELDIST_TO_ANGLE
)
ftheta.ftheta_param.pixeldist_to_angle_poly.extend([0.0, 0.00106, 1.4e-08])
ftheta.ftheta_param.max_angle = 1.36
out["CameraSpec/ftheta"] = ftheta.SerializeToString()

req = sensorsim_pb2.RGBRenderRequest()
req.scene_id = "clipgt-01d503d4-449b-46fc-8d78-9085e70d3554"
req.resolution_w, req.resolution_h = 1900, 1080
req.camera_intrinsics.CopyFrom(spec)
req.frame_start_us = 1759000000123456
req.frame_end_us = 1759000000153456
req.sensor_pose.start_pose.CopyFrom(pose(1.9, -0.06, 1.3))
req.sensor_pose.end_pose.CopyFrom(pose(2.0, -0.07, 1.31))
for track_id in ("28", "EGO", "traffic-7"):
    obj = req.dynamic_objects.add()
    obj.track_id = track_id
    obj.pose_pair.start_pose.CopyFrom(pose(10.0, 2.0, 0.0))
    obj.pose_pair.end_pose.CopyFrom(pose(10.5, 2.0, 0.0))
req.image_format = sensorsim_pb2.ImageFormat.JPEG
req.image_quality = 95.0
req.insert_ego_mask = False
out["RGBRenderRequest/full"] = req.SerializeToString()

ret = sensorsim_pb2.RGBRenderReturn()
ret.image_bytes = bytes(range(256)) * 4
out["RGBRenderReturn"] = ret.SerializeToString()

agg = sensorsim_pb2.AggregatedRenderRequest()
for _ in range(3):
    agg.rgb_requests.add().CopyFrom(req)
out["AggregatedRenderRequest"] = agg.SerializeToString()

aggret = sensorsim_pb2.AggregatedRenderReturn()
for _ in range(3):
    aggret.rgb_returns.add().CopyFrom(ret)
out["AggregatedRenderReturn"] = aggret.SerializeToString()

cams_req = sensorsim_pb2.AvailableCamerasRequest()
cams_req.scene_id = "clipgt-01d503d4"
out["AvailableCamerasRequest"] = cams_req.SerializeToString()

cams = sensorsim_pb2.AvailableCamerasReturn()
for logical_id in ("front_wide", "cross_left", "cross_right", "front_tele"):
    cam = cams.available_cameras.add()
    cam.logical_id = logical_id
    cam.intrinsics.CopyFrom(spec)
    cam.rig_to_camera.CopyFrom(pose(2.0, -0.06, 1.59))
out["AvailableCamerasReturn"] = cams.SerializeToString()

# logging.proto: the .asl envelope. Only the variants the bridge reads.
entry = logging_pb2.LogEntry()
entry.render_request.CopyFrom(req)
out["LogEntry/render_request"] = entry.SerializeToString()

entry2 = logging_pb2.LogEntry()
entry2.available_cameras_return.CopyFrom(cams)
out["LogEntry/available_cameras_return"] = entry2.SerializeToString()

meta = logging_pb2.RolloutMetadata()
meta.session_metadata.scene_id = "clipgt-01d503d4"
aabb = meta.actor_definitions.actor_aabb.add()
aabb.actor_id = "EGO"
aabb.actor_label = "automobile"
aabb.aabb.size_x, aabb.aabb.size_y, aabb.aabb.size_z = 5.207, 2.157, 1.823
entry3 = logging_pb2.LogEntry()
entry3.rollout_metadata.CopyFrom(meta)
out["LogEntry/rollout_metadata"] = entry3.SerializeToString()

poses = logging_pb2.ActorPoses()
poses.timestamp_us = 1759000000123456
for track_id in ("EGO", "28"):
    ap = poses.actor_poses.add()
    ap.actor_id = track_id
    ap.actor_pose.CopyFrom(pose(3.0, 4.0, 0.0))
entry4 = logging_pb2.LogEntry()
entry4.actor_poses.CopyFrom(poses)
out["LogEntry/actor_poses"] = entry4.SerializeToString()

print(json.dumps({k: v.hex() for k, v in out.items()}))
'''


def generate(protos: Path, dest: Path) -> None:
    """Compile a directory of .proto files into an importable package."""
    package = dest / "alpasim_grpc" / "v0"
    package.mkdir(parents=True, exist_ok=True)
    for name in ("alpasim_grpc", "alpasim_grpc/v0"):
        (dest / name / "__init__.py").write_text("")
    staged = dest / "_src"
    (staged / "alpasim_grpc" / "v0").mkdir(parents=True, exist_ok=True)
    for proto in protos.glob("*.proto"):
        shutil.copy(proto, staged / "alpasim_grpc" / "v0" / proto.name)
    subprocess.run(
        [
            sys.executable, "-m", "grpc_tools.protoc",
            f"-I{staged}",
            f"--python_out={dest}",
            f"--grpc_python_out={dest}",
            *[str(p) for p in (staged / "alpasim_grpc" / "v0").glob("*.proto")],
        ],
        check=True,
        capture_output=True,
    )


def encode(stub_dir: Path, script: Path) -> Dict[str, str]:
    result = subprocess.run(
        [sys.executable, str(script), str(stub_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"corpus encoding failed under {stub_dir.name}:\n{result.stderr}"
        )
    return json.loads(result.stdout)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream",
        required=True,
        help="path to the 0.55.0 alpasim_grpc/v0 proto directory",
    )
    parser.add_argument(
        "--vendored",
        default=str(REPO / "proto" / "alpasim_grpc" / "v0"),
        help="path to this repo's pinned 0.54.0 protos",
    )
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        script = root / "corpus.py"
        script.write_text(CORPUS_SOURCE)

        results = {}
        for label, protos in (
            ("0.54.0 (vendored)", Path(args.vendored)),
            ("0.55.0 (upstream)", Path(args.upstream)),
        ):
            dest = root / label.split()[0].replace(".", "_")
            generate(protos, dest)
            results[label] = encode(dest, script)

        left, right = results["0.54.0 (vendored)"], results["0.55.0 (upstream)"]

    names = sorted(set(left) | set(right))
    mismatched, missing = [], []
    for name in names:
        if name not in left or name not in right:
            missing.append(name)
        elif left[name] != right[name]:
            mismatched.append(name)

    width = max(len(n) for n in names)
    for name in names:
        if name in missing:
            status = "ONLY IN ONE GENERATION"
        elif name in mismatched:
            status = f"DIFFERS ({len(left[name]) // 2} vs {len(right[name]) // 2} bytes)"
        else:
            status = f"identical ({len(left[name]) // 2} bytes)"
        print(f"  {name:<{width}}  {status}")

    print()
    if mismatched or missing:
        print(
            f"FAIL: {len(mismatched)} message(s) encode differently, "
            f"{len(missing)} present in only one generation."
        )
        return 1
    print(
        f"PASS: all {len(names)} shared messages encode byte-identically "
        f"under 0.54.0 and 0.55.0."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
