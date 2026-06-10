#!/usr/bin/env python
"""Gate G3 validation: inspect a closed-loop run directory.

Checks (all scripted):
  * a rollout.asl exists under <run-dir>/rollouts/**;
  * ego displacement over the rollout (first->last EGO actor_poses entry,
    xy norm) exceeds --min-displacement meters (the policy actually drove);
  * renders a video artifact from the driver_camera_image frames recorded in
    the .asl (what the policy actually saw, i.e. our CARLA frames);
  * inventories scorer/eval outputs found in the run dir.

Writes a summary JSON next to the video.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alpasim_carla.aslio import read_log_entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--min-displacement", type=float, default=10.0)
    parser.add_argument("--camera", default="camera_front_wide_120fov")
    parser.add_argument("--fps", type=int, default=10)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"run_dir": str(run_dir), "checks": {}, "failures": []}

    asl_files = sorted(run_dir.glob("rollouts/**/rollout.asl"))
    summary["rollout_asl"] = [str(p) for p in asl_files]
    if not asl_files:
        summary["failures"].append("no rollout.asl produced")
        _finish(summary, out_dir)
        return 1
    asl = asl_files[0]

    ego_poses = []
    frames = []
    render_requests = 0
    for entry in read_log_entries(str(asl)):
        kind = entry.WhichOneof("log_entry")
        if kind == "actor_poses":
            for ap in entry.actor_poses.actor_poses:
                if ap.actor_id == "EGO":
                    v = ap.actor_pose.vec
                    ego_poses.append((entry.actor_poses.timestamp_us, v.x, v.y, v.z))
        elif kind == "driver_camera_image":
            image = entry.driver_camera_image.camera_image
            if image.logical_id == args.camera:
                frames.append((image.frame_start_us, bytes(image.image_bytes)))
        elif kind == "render_request":
            render_requests += 1

    summary["checks"]["ego_pose_count"] = len(ego_poses)
    summary["checks"]["render_requests_logged"] = render_requests
    summary["checks"]["video_frames"] = len(frames)

    if len(ego_poses) >= 2:
        _, x0, y0, _ = ego_poses[0]
        _, x1, y1, _ = ego_poses[-1]
        displacement = math.hypot(x1 - x0, y1 - y0)
        # Also track path length (rules out "teleported once" artifacts).
        path = sum(
            math.hypot(b[1] - a[1], b[2] - a[2])
            for a, b in zip(ego_poses, ego_poses[1:])
        )
        summary["checks"]["ego_displacement_m"] = round(displacement, 2)
        summary["checks"]["ego_path_length_m"] = round(path, 2)
        if displacement <= args.min_displacement:
            summary["failures"].append(
                f"ego displacement {displacement:.2f}m <= required "
                f"{args.min_displacement}m"
            )
    else:
        summary["failures"].append("fewer than 2 EGO poses in rollout.asl")

    # Scorer / eval outputs anywhere in the run dir.
    scorer_files = [
        str(p)
        for pattern in ("*score*", "*eval*", "*metric*")
        for p in run_dir.rglob(pattern)
        if p.is_file() and "config" not in p.name
    ]
    summary["scorer_outputs"] = sorted(set(scorer_files))
    if not summary["scorer_outputs"]:
        summary["failures"].append("no scorer/eval output files found in run dir")

    # Video artifact from the frames the driver received.
    if frames:
        frames.sort()
        with tempfile.TemporaryDirectory() as tmp:
            for i, (_, data) in enumerate(frames):
                (Path(tmp) / f"frame_{i:05d}.jpg").write_bytes(data)
            video_path = out_dir / "g3_front_wide.mp4"
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-framerate", str(args.fps),
                    "-i", f"{tmp}/frame_%05d.jpg",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                    str(video_path),
                ],
                capture_output=True,
            )
            if result.returncode == 0:
                summary["video"] = str(video_path)
            else:
                summary["failures"].append(
                    f"ffmpeg failed: {result.stderr.decode()[-300:]}"
                )
    else:
        summary["failures"].append(f"no {args.camera} frames recorded in rollout.asl")

    return _finish(summary, out_dir)


def _finish(summary: dict, out_dir: Path) -> int:
    summary["passed"] = not summary["failures"]
    path = out_dir / "g3_summary.json"
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"validate_rollout: {'PASS' if summary['passed'] else 'FAIL'} -> {path}")
    for failure in summary["failures"]:
        print(f"  FAIL: {failure}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
