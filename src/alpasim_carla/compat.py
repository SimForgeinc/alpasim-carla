"""Server compatibility: the handshake the bridge performs before rendering.

Two questions, both answered by pure functions so they are testable without a
simulator (gate G1):

  * is this the CARLA build we were pinned against?
  * is the world currently loaded the map the scene manifest asked for?

Both were previously advisory. The version check logged a warning and carried
on; the map check used ``current.endswith(scene.carla_map)``, which accepts a
manifest name that is merely a suffix of the server's map - a manifest saying
``Belmont`` matched a server serving ``Munich_Belmont``. Both failure modes are
silent, and both surface much later as a wrong-looking render rather than a
refusal to start.
"""

from __future__ import annotations

from typing import Optional


class ServerMismatch(RuntimeError):
    """The connected CARLA server is not the one this scene expects."""


def normalize_map_name(name: str) -> str:
    """Reduce a CARLA map name to a comparable basename.

    Handles the three shapes seen in the wild: a bare ``Town10HD_Opt``, the
    0.9.x ``Carla/Maps/Town10HD_Opt``, and the UE5 content path
    ``/Game/Carla/Maps/Town10HD_Opt``. The ``_Opt`` suffix marks the
    layer-optimised variant of the same town, so it is not part of identity.
    """
    basename = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    lowered = basename.strip().lower()
    if lowered.endswith("_opt"):
        lowered = lowered[: -len("_opt")]
    return lowered


def map_names_match(server_map: str, manifest_map: str) -> bool:
    """True when both names denote the same town, ignoring path and ``_Opt``."""
    return normalize_map_name(server_map) == normalize_map_name(manifest_map)


def version_matches(server_version: str, expected_version: str) -> bool:
    """True when the server reports the expected release.

    A prefix match, because servers append build metadata (``0.10.0-dirty``,
    ``0.10.0+ue5``) and the pin is the release, not the build.
    """
    return server_version.strip().startswith(expected_version.strip())


def check_server(
    *,
    server_version: str,
    server_map: str,
    expected_version: Optional[str],
    expected_map: Optional[str],
) -> None:
    """Raise :class:`ServerMismatch` unless the server matches expectations.

    Either expectation may be ``None`` to skip that half of the check. Errors
    name both sides so the log says what was found as well as what was wanted.
    """
    if expected_version is not None and not version_matches(
        server_version, expected_version
    ):
        raise ServerMismatch(
            f"CARLA server reports version {server_version!r} but this scene "
            f"expects {expected_version!r}; refusing to start. Set "
            f"--expect-carla-version '' to disable this check."
        )
    if expected_map is not None and not map_names_match(server_map, expected_map):
        raise ServerMismatch(
            f"CARLA server has map {server_map!r} (normalized "
            f"{normalize_map_name(server_map)!r}) but the scene manifest asks "
            f"for {expected_map!r} (normalized "
            f"{normalize_map_name(expected_map)!r})."
        )
