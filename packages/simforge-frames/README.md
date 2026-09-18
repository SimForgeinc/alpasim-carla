# simforge-frames

The AlpaSim ↔ Unreal coordinate conversions, as a distribution of their own.

`numpy` and nothing else. No protobuf, no gRPC, no CARLA — which is the
entire reason it exists.

## Why it is separate

`alpasim-carla` carries generated stubs for `alpasim_grpc` 0.54.0;
`simforge-closed-loop` carries 0.55.0. Both declare the proto package
`common`, and protobuf's descriptor pool is global, so importing both into
one interpreter fails with `duplicate symbol 'common.Empty'` (see
`simforge-closed-loop/docs/adr/ADR-017`).

This module is the one piece both sides genuinely need — `traffic-scripted`
converts agent poses with it, and ADR-015's camera attach converts
`rig_to_camera` with it — and it is the worst possible candidate for
duplication, because the y-flip is where a second copy would silently
diverge and the round-trip test that catches that lives here.

Splitting it out means the closed-loop repo depends on **this** rather than
on the bridge, and never loads a second proto generation.

`alpasim_carla.frames` re-exports this package verbatim, so the bridge's
own imports are unchanged.
