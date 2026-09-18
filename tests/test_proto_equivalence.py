"""The sensorsim wire seam is unchanged by the alpasim_grpc 0.54.0 -> 0.55.0 bump.

No CARLA and no server, but it does need the upstream proto tree and
grpcio-tools, so it skips when either is missing. Point it at a checkout:

    ALPASIM_PROTO_DIR=/path/to/alpasim/src/grpc/alpasim_grpc/v0 pytest tests/

0.55.0 adds batch_render_rgb and get_loaded_scenes to sensorsim.proto and
fields to logging.proto, and separately removes an RPC and renames map_id to
scene_id in traffic.proto. Only sensorsim and logging touch this bridge. If
the messages both generations share encode to identical bytes, a 0.55.0
client and this repo's 0.54.0 server agree on the wire and the bump cannot
break rendering - which is the only part Stage C depends on.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
UPSTREAM = os.environ.get("ALPASIM_PROTO_DIR", "")


@pytest.mark.skipif(not UPSTREAM, reason="ALPASIM_PROTO_DIR not set")
def test_shared_messages_encode_identically_under_both_generations():
    pytest.importorskip("grpc_tools", reason="grpcio-tools not installed")
    upstream = Path(UPSTREAM)
    if not (upstream / "sensorsim.proto").is_file():
        pytest.skip(f"no sensorsim.proto under {upstream}")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "proto_equivalence.py"),
            "--upstream",
            str(upstream),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"proto equivalence failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout
