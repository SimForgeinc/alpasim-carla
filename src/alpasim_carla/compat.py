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

import re
from typing import Mapping, Optional

# A release string starts with two dotted numbers: 0.9.16, 0.10.0, 0.10.0-ue5.
# Anything else - notably a bare git hash like "fa7751a", which is what the G3
# evidence server reported - is a build nobody can name.
_RELEASE_RE = re.compile(r"^\d+\.\d+")


class ServerMismatch(RuntimeError):
    """The connected CARLA server is not the one this scene expects."""


def looks_like_release(version: str) -> bool:
    return bool(_RELEASE_RE.match(version.strip()))


def resolve_expected_version(
    scenes: Mapping[str, object], flag: Optional[str]
) -> Optional[str]:
    """Decide which CARLA version to demand, manifest first.

    The expected version is a property of the scene - a scene recorded on a
    0.9.16 twin says ``carla_version: 0.9.16``, the Belmont scene says
    ``0.10.0`` - so the manifest is the source of truth and the CLI flag only
    overrides it.

    ``flag`` of ``None`` means "use the manifests"; an empty string means
    "skip the check entirely". Scenes that omit the field abstain rather than
    veto, so one versioned manifest is enough. Manifests that disagree are an
    error: one process serves one server.
    """
    if flag is not None:
        return flag.strip() or None

    declared = {
        getattr(scene, "carla_version", None)
        for scene in scenes.values()
        if getattr(scene, "carla_version", None)
    }
    if not declared:
        return None
    if len(declared) > 1:
        detail = ", ".join(
            f"{getattr(scene, 'scene_id', key)}={getattr(scene, 'carla_version')!r}"
            for key, scene in sorted(scenes.items())
            if getattr(scene, "carla_version", None)
        )
        raise ServerMismatch(
            f"scene manifests disagree about carla_version ({detail}); one "
            f"bridge process serves one server. Split them across processes "
            f"or override with --expect-carla-version."
        )
    return declared.pop()


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
        if looks_like_release(server_version):
            hint = (
                "Set carla_version in the scene manifest to the version this "
                "scene was recorded against, or override with "
                "--expect-carla-version."
            )
        else:
            hint = (
                f"The server reports a git hash, not a release, so its API "
                f"surface cannot be inferred. To accept it deliberately, set "
                f"carla_version: {server_version!r} in the scene manifest."
            )
        raise ServerMismatch(
            f"CARLA server reports version {server_version!r} but this scene "
            f"expects {expected_version!r}; refusing to start. {hint}"
        )
    if expected_map is not None and not map_names_match(server_map, expected_map):
        raise ServerMismatch(
            f"CARLA server has map {server_map!r} (normalized "
            f"{normalize_map_name(server_map)!r}) but the scene manifest asks "
            f"for {expected_map!r} (normalized "
            f"{normalize_map_name(expected_map)!r})."
        )


class ClientMismatch(RuntimeError):
    """The CARLA client wheel does not match the server it is talking to.

    Distinct from :class:`ServerMismatch`, which is about the SCENE: that one
    asks whether the server is the one a manifest was recorded against. This
    one asks whether the library in this process speaks the server's protocol
    at all, and it is the check that was missing.
    """


def check_client(*, client_version: str, server_version: str) -> None:
    """Raise :class:`ClientMismatch` unless the wheel matches the server.

    CARLA itself only WARNS here - it prints "Version mismatch detected" to
    stderr and connects anyway. What follows is not a clean failure: the
    first Belmont campaign ran a 0.9.16 client against the 0.10 server,
    loaded the map, and hung before the first policy decision with nothing in
    any log naming the cause.

    The comparison is exact rather than by major.minor. Two CARLA releases
    that disagree in the patch position have disagreed about the Python API
    before, and a renderer is the wrong place to be generous: the wheel is
    pinned by the server image it was copied out of, so an exact match is
    always achievable and an inexact one is always a mistake.
    """
    if client_version == server_version:
        return
    raise ClientMismatch(
        f"CARLA client wheel is {client_version!r} and the server is "
        f"{server_version!r}; refusing to start. CARLA only warns about this "
        f"and then connects, which is how it costs a campaign rather than a "
        f"startup.\n"
        f"The wheel ships INSIDE the server image and decides the "
        f"interpreter: the Belmont 0.10 image carries only "
        f"carla-0.10.0-cp310, so a 0.10 renderer runs on Python 3.10. Copy "
        f"the wheel out of the image you are running against and install it "
        f"into an interpreter its tag allows."
    )
