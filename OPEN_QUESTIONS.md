# Open questions

Per the engineering policy (PLAN.md §2): every interface claim must trace to
the pinned protos, replayed `.asl` traffic, or the vendored runtime source.
What can't be verified from those is recorded here — implemented behavior is
the documented assumption, never a silent guess.

1. **Request resolution vs intrinsics resolution.** Real traffic requests
   1080×1900 with native-1080×1920 intrinsics. NuRec's crop-vs-scale
   semantics are unobservable (render responses aren't logged, NuRec is
   closed). **Assumption implemented:** the request is a center crop of the
   native sensor; rendered FOV is the angle subtended by the requested width
   (documented in docs/CONTRACT.md, `cameras.resolve_camera`). At the
   observed 20px delta the FOV difference is < 0.7°.

2. **Pose instant within a PosePair.** Requests carry start/end poses for a
   ~30 ms shutter window. NuRec presumably integrates (rolling shutter /
   motion blur). **Assumption implemented:** render a single instant at
   `start_pose` (matches `frame_start_us`, which is also the timestamp the
   driver-image correlation uses). Roadmap: rolling-shutter simulation.

3. **Does the alpamayo driver rectify with runtime-passed intrinsics or its
   own baked calibration?** Affects how much the pinhole approximation hurts
   the policy. *Empirical G3 result (2026-06-10): with the recorded ftheta
   rig approximated as pinhole, alpamayo1_5 drove 61.9 m lane-aligned over a
   20 s rollout in Town10 — the approximation is policy-usable. How much
   driving quality it costs versus true ftheta rendering remains unmeasured
   (roadmap: distortion post-warp).*

4. **`AvailableCamera.rig_to_camera` field naming.** The proto comment warns
   the field "should be camera_to_rig". The runtime composes
   `ego_pose @ rig_to_camera` to get `sensor_pose`, and the recorded values
   (e.g. front camera at vec≈(1.9, -0.06, 1.3)) are camera-in-rig
   coordinates — so the field VALUE is the camera pose in the rig frame
   (active rig→camera transform) regardless of the name. We serve the same
   convention we recorded.

5. **`render_aggregated` response metadata.** The runtime code at a1f05bb
   reads `rgb_responses[i].start_timestamp_us/camera_logical_id`, fields that
   don't exist in the generated stubs (dead code; default path is
   `render_rgb`). We implement the stub-faithful shape (`rgb_returns`,
   `image_bytes` only). If a future AlpaSim flips `use_aggregated_render` on,
   re-pin and revisit.

6. **Ego masks.** v0.1 publishes none; the runtime then sends
   `insert_ego_mask=false` (verified in `determine_ego_mask_id`). Whether
   alpamayo quality depends on hood masking in CARLA imagery is empirical —
   G3 will tell.
