import sys
from pathlib import Path

import pytest

# Allow running the suite from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def pytest_addoption(parser):
    parser.addoption(
        "--run-mutating",
        action="store_true",
        default=False,
        help="also run tests marked carla_mutating, which change server state "
        "(load_world). Off by default so `-m carla` is idempotent against a "
        "shared CARLA server.",
    )


def pytest_collection_modifyitems(config, items):
    """Skip carla_mutating tests unless --run-mutating is given.

    A marker alone would not do this: `-m carla` selects everything carrying
    the carla marker, including the mutating ones. Gating on an explicit flag
    keeps the default run safe on a server that is hosting campaign runs.
    """
    if config.getoption("--run-mutating"):
        return
    skip = pytest.mark.skip(
        reason="mutates server state (load_world); pass --run-mutating to include"
    )
    for item in items:
        if "carla_mutating" in item.keywords:
            item.add_marker(skip)
