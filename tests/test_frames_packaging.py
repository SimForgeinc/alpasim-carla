"""simforge-frames must stay importable without the proto stubs.

That is the whole reason it is a separate distribution: simforge-closed-loop
generates alpasim_grpc 0.55.0 stubs and this package carries 0.54.0, both
declaring the proto package `common`, and protobuf's descriptor pool is
global. If this module ever grows a proto import, the closed-loop repo
silently gains a second generation and dies with `duplicate symbol
'common.Empty'` in whichever process loads both.
"""

import subprocess
import sys

CHECK = """
import sys
import simforge_frames
loaded = sorted(m for m in sys.modules if "_pb2" in m or "_proto" in m)
print(",".join(loaded))
"""


def test_importing_simforge_frames_loads_no_protobuf_modules():
    result = subprocess.run(
        [sys.executable, "-c", CHECK], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", (
        f"simforge_frames pulled in proto modules: {result.stdout.strip()}. "
        f"It must stay proto-free - see ADR-017."
    )


def test_the_bridge_shim_re_exports_the_same_objects():
    """alpasim_carla.frames must not become a second implementation."""
    import simforge_frames

    from alpasim_carla import frames

    for name in ("rotator_from_quat", "quat_from_rotator", "apply_anchor",
                 "carla_transform_tuple", "compose", "inverse"):
        assert getattr(frames, name) is getattr(simforge_frames, name), (
            f"{name} differs between alpasim_carla.frames and simforge_frames"
        )
