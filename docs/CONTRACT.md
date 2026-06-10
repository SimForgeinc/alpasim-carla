# docs/CONTRACT.md — the SensorsimService contract as implemented

This document is the library's spine: for each of the 8 RPCs, every request
field we consume (units, coordinate frame, conventions) and every response
field we produce, with proto excerpts from the pinned contract
(AlpaSim `a1f05bb628f3`, `alpasim_grpc` 0.54.0, proto package
`nre.grpc.protos.sensorsim` — the namespace that keeps us wire-compatible).
**PRs that change behavior must change this file.**

Shared conventions (from `common.proto` + AlpaSim CONTRIBUTING.md):

* `common.Pose { Vec3 vec; Quat quat }` — ACTIVE transform parent→child;
  quat order `(w, x, y, z)`; standard SE(3) composition (`t = t₁ + R₁t₂`,
  verified against `alpasim_utils.geometry.Pose`). Meters.
* `local` frame: right-handed ENU, z-up. `rig`/`aabb` body frames:
  x-forward/y-left/z-up; `aabb` origin is the bounding-box CENTER.
  Camera frames: CV optical x-right/y-down/z-forward.
* Timestamps: `fixed64` microseconds.

---

## render_rgb(RGBRenderRequest) → RGBRenderReturn

```proto
message RGBRenderRequest {
  string scene_id = 1;
  uint32 resolution_h = 2;        uint32 resolution_w = 3;
  CameraSpec camera_intrinsics = 4;
  fixed64 frame_start_us = 5;     fixed64 frame_end_us = 6;
  PosePair sensor_pose = 7;       // local→camera (optical), start & end of frame
  repeated DynamicObject dynamic_objects = 8;  // {track_id, pose_pair}: local→aabb
  ImageFormat image_format = 9;   float image_quality = 10;
  bool insert_ego_mask = 11;      EgoMaskId ego_mask_id = 12;
}
message RGBRenderReturn { bytes image_bytes = 1; }
```

Consumed:
* `scene_id` — must match a loaded scene manifest, else **NOT_FOUND** listing
  available scenes.
* `resolution_w/h` — the exact output size in pixels. May differ from the
  intrinsics' native resolution; treated as a CENTER CROP of the native
  sensor when deriving FOV (OPEN_QUESTIONS #1).
* `camera_intrinsics` — see CameraSpec handling below.
* `sensor_pose.start_pose` — local→camera (optical convention) pose at
  `frame_start_us`; the camera is placed there. `end_pose` is read but not
  used in v0.1 (single-instant render; OPEN_QUESTIONS #2).
* `dynamic_objects[*].track_id` — registry key (spawn/teleport/despawn).
  `pose_pair.start_pose` — local→aabb (bbox CENTER) pose; the actor is
  teleported so its bounding-box center lands exactly there (CARLA pivot
  offset compensated via `actor.bounding_box.location`). Physics and
  autopilot are OFF for all bridge-managed actors — AlpaSim owns motion.
  Objects whose label/dims have no blueprint mapping get the documented box
  prop fallback + a structured warning; objects are never silently dropped.
* `image_format` — PNG(1) and JPEG(2) supported (matching AlpaSim's own
  support note in the proto); anything else → **INVALID_ARGUMENT**.
  `image_quality` — JPEG quality (real traffic uses 95).
* `insert_ego_mask`/`ego_mask_id` — we publish no ego masks (below), so
  `insert_ego_mask=true` → **INVALID_ARGUMENT**.

Produced: `image_bytes` — the encoded frame, exactly `resolution_w×resolution_h`.

### CameraSpec handling

```proto
message CameraSpec {
  oneof camera_param { FthetaCameraParam ftheta_param = 2;
                       OpenCVPinholeCameraParam opencv_pinhole_param = 3;
                       OpenCVFisheyeCameraParam opencv_fisheye_param = 4; }
  string logical_id = 5;
  uint32 resolution_h = 7;  uint32 resolution_w = 8;
  ShutterType shutter_type = 9;
  oneof external_distortion { BivariateWindshieldModelParameters … = 10; }
}
```

CARLA renders an ideal centered pinhole only. Native support:
`opencv_pinhole_param` with zero distortion, principal point within 2% of
center, GLOBAL/UNKNOWN shutter → `fov = 2·atan((resolution_w/2)/fx)`.
Everything else fails with **INVALID_ARGUMENT naming the field** unless the
server runs with `--allow-pinhole-approximation`, which enables (and logs as
structured approximation notes):
* `ftheta_param` → hfov from `pixeldist_to_angle_poly` evaluated at the
  requested half-width (recorded hyperion 120fov poly ⇒ 120.0°); capped at
  `max_angle`; ≥170° total is rejected (pinhole cannot represent it).
* `opencv_fisheye_param` → equidistant `θ = r/fx`.
* nonzero pinhole distortion / off-center principal point / windshield
  model → ignored, noted.
* rolling `shutter_type` → rendered as global shutter, noted.

## render_lidar(LidarRenderRequest) → LidarRenderReturn

Out of scope for v0.1 (roadmap). CARLA backend → **UNIMPLEMENTED** with that
statement. The synthetic backend answers `num_points=0` so contract tooling
can exercise all 8 RPCs.

## render_aggregated(AggregatedRenderRequest) → AggregatedRenderReturn

Faithful to the generated stubs: `rgb_returns[i] = RGBRenderReturn` for
`rgb_requests[i]` (same path as render_rgb), `lidar_returns` per
render_lidar, `driver_data` left empty. Note: unused by the runtime at the
pinned commit (OPEN_QUESTIONS #5).

## get_version(Empty) → common.VersionId

Produces `version_id = "alpasim-carla <version> (<backend>)"`, `git_hash` of
this repo, and `grpc_api_version = 0.54.0` — the `alpasim_grpc` distribution
version at the pinned commit. The runtime probes this at startup and asserts
consistency across replicas.

## get_available_scenes(Empty) → common.AvailableScenesReturn

The scene ids of all loaded manifests, sorted. The runtime validates its
configured scenes against this list (or `"*"`, which we only advertise with
an explicit server flag).

## get_available_cameras(AvailableCamerasRequest) → AvailableCamerasReturn

Per scene manifest: `{intrinsics: CameraSpec, rig_to_camera: common.Pose,
logical_id}` per camera. The VALUE of `rig_to_camera` is the camera pose in
the rig frame (active rig→camera; the proto comment notes the name is
contested — OPEN_QUESTIONS #4); the runtime composes
`ego_local_to_rig @ rig_to_camera` to build `sensor_pose`. **The runtime
treats this RPC as the source of truth for cameras** (local config can
modify but not add — `camera_catalog.merge_local_and_sensorsim_cameras`), so
manifests must cover every logical id the driver uses (alpamayo1:
`camera_cross_left_120fov`, `camera_front_wide_120fov`,
`camera_cross_right_120fov`, `camera_front_tele_30fov`).

## get_available_trajectories(AvailableTrajectoriesRequest) → AvailableTrajectoriesReturn

Empty list. Never called by the runtime at the pinned commit; matches
NVIDIA's own replay servicer behavior. Unknown scene_id still → NOT_FOUND.

## get_available_ego_masks(Empty) → AvailableEgoMasksReturn

Empty list in v0.1: the runtime then resolves `ego_mask_id=None` and sends
`insert_ego_mask=false` on every render request (verified in
`alpasim_runtime.services.sensorsim_service.determine_ego_mask_id`).
