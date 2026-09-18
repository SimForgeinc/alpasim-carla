"""Acceptance tests for this branch, against a live CARLA server.

These are the day-one checks. They are the branch's acceptance criteria: the
0.10 port is not done until they pass against
``ghcr.io/abhisheksimforgeai/carla-rfs-munich-belmont:0.10.0``. Every one of
them is currently unverified - no 0.10 server was reachable when the branch
was written.

All are marked ``carla``, so the simulator-free suite is unaffected::

    pytest tests/ -m "not carla"              # simulator-free, anywhere
    pytest tests/ -m carla                    # needs a server; read-only
    pytest tests/ -m carla --run-mutating     # also reloads the map

Configure via environment:

    CARLA_HOST                 default 127.0.0.1
    CARLA_PORT                 default 2000
    CARLA_MAP                  default Town10HD_Opt - the map to expect
    CARLA_EXPECT_VERSION       overrides the manifests' carla_version;
                               unset means the manifests decide
    ALPASIM_BLUEPRINT_CATALOG  listing from tools/list_blueprints.py;
                               when unset the curated 0.9.16 table is used
                               and the catalogue-agreement test is skipped
"""

import logging
import os
import time

import pytest

from alpasim_carla.catalog import default_catalog, load_catalog
from alpasim_carla.compat import (
    check_server,
    map_names_match,
    normalize_map_name,
    resolve_expected_version,
)
from alpasim_carla.registry import audit_scene_blueprints
from alpasim_carla.scenes import load_scene_dir

pytestmark = pytest.mark.carla

HOST = os.environ.get("CARLA_HOST", "127.0.0.1")
PORT = int(os.environ.get("CARLA_PORT", "2000"))
MAP = os.environ.get("CARLA_MAP", "Town10HD_Opt")
EXPECT_VERSION = os.environ.get("CARLA_EXPECT_VERSION", "")
CATALOG_PATH = os.environ.get("ALPASIM_BLUEPRINT_CATALOG", "")


@pytest.fixture(scope="module")
def client():
    carla = pytest.importorskip("carla", reason="CARLA client wheel not installed")
    handle = carla.Client(HOST, PORT)
    handle.set_timeout(60.0)
    try:
        handle.get_server_version()
    except RuntimeError as exc:
        pytest.fail(
            f"no CARLA server at {HOST}:{PORT} ({exc}). These tests are "
            f"marked 'carla'; run the simulator-free suite with -m 'not carla'."
        )
    return handle


@pytest.fixture(scope="module")
def world(client):
    return client.get_world()


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(CATALOG_PATH) if CATALOG_PATH else default_catalog()


# -- handshake ----------------------------------------------------------------


def test_server_reports_the_version_the_manifests_declare(client):
    """EXPECT_VERSION overrides; otherwise the shipped manifests decide."""
    expected = EXPECT_VERSION or resolve_expected_version(
        load_scene_dir("scenes/examples"), flag=None
    )
    if expected is None:
        pytest.skip(
            "no carla_version in scenes/examples and CARLA_EXPECT_VERSION "
            "unset; nothing to check"
        )
    check_server(
        server_version=client.get_server_version(),
        server_map="",
        expected_version=expected,
        expected_map=None,
    )


def test_loaded_map_matches_the_configured_map_name(world):
    """Records the exact string 0.10 returns. 0.9.x reports
    'Carla/Maps/Town10HD_Opt'; UE5 is expected to report a content path."""
    name = world.get_map().name
    assert map_names_match(name, MAP), (
        f"server map {name!r} normalizes to {normalize_map_name(name)!r}, "
        f"manifest expects {normalize_map_name(MAP)!r}"
    )


@pytest.mark.carla_mutating
def test_map_name_survives_a_reload_unchanged(client, record_property):
    """A reload must land on the same normalized name, or _ensure_scene will
    reload on every single request.

    Also the only place that measures how long load_world takes on this
    server - a number the Stage B tick budget needs and nobody has yet. Both
    timings are logged and recorded as test properties.

    Mutating: it loads a map. Restores the entry map on the way out, and
    refuses to run at all if the entry map is not the target, so it can never
    leave a shared server on a map nobody asked for.
    """
    entry = client.get_world().get_map().name
    if not map_names_match(entry, MAP):
        pytest.skip(
            f"server is on {entry!r}, not the target {MAP!r}; refusing to "
            f"reload a server that is mid-campaign. Set CARLA_MAP to the "
            f"current map, or load it first."
        )

    start = time.perf_counter()
    after = client.load_world(MAP).get_map().name
    load_seconds = time.perf_counter() - start

    restore_start = time.perf_counter()
    client.load_world(MAP)
    restore_seconds = time.perf_counter() - restore_start

    record_property("load_world_seconds", round(load_seconds, 3))
    record_property("restore_load_world_seconds", round(restore_seconds, 3))
    record_property("map_name_entry", entry)
    record_property("map_name_after_load", after)
    logging.getLogger(__name__).warning(
        "load_world(%s) took %.2fs (restore %.2fs); map name %r -> %r",
        MAP, load_seconds, restore_seconds, entry, after,
    )

    assert normalize_map_name(entry) == normalize_map_name(after)


# -- blueprint catalogue ------------------------------------------------------


def test_a_terminal_prop_exists_for_the_ladder(world, catalog):
    """Without this the ladder's last rung raises instead of degrading."""
    library = world.get_blueprint_library()
    assert list(library.filter(catalog.fallback_prop)), (
        f"catalogue names {catalog.fallback_prop!r} as the terminal fallback "
        f"but this server has no such blueprint"
    )


def test_every_catalogued_blueprint_exists_on_this_server(world, catalog):
    """A stale listing makes choose_blueprint trust an id that find() will
    reject, which _spawn now raises BlueprintUnavailable for."""
    if not CATALOG_PATH:
        pytest.skip("no ALPASIM_BLUEPRINT_CATALOG; the 0.9.16 default is "
                    "known-wrong on 0.10")
    library = world.get_blueprint_library()
    live = {b.id for b in library}
    missing = sorted(catalog.available - live)
    assert not missing, f"catalogue {catalog.source} lists absent ids: {missing}"


def test_the_catalogue_has_vehicles_and_a_walker(catalog):
    assert catalog.vehicles, "no vehicle candidates; every car becomes a prop"
    assert catalog.walker, "no walker candidate; every pedestrian becomes a prop"


# -- the ladder against real scenes -------------------------------------------


@pytest.mark.parametrize("scenes_dir", ["scenes/examples", "scenes/g3"])
def test_no_shipped_scene_actor_degrades_to_the_prop(scenes_dir, catalog):
    """Gate G2's check, widened to cyclists and motorcycles: a run where a
    gated actor became a box scores nothing."""
    degraded = {}
    for scene in load_scene_dir(scenes_dir).values():
        for track_id, label in audit_scene_blueprints(scene, catalog).items():
            degraded[f"{scene.scene_id}/{track_id}"] = label
    assert not degraded, (
        f"gated actors would render as {catalog.fallback_prop}: {degraded}"
    )


# -- weather ------------------------------------------------------------------


def test_setting_weather_never_aborts_a_render(world):
    """0.10 documents weather as unsupported on the release map. Whether the
    call raises or no-ops is unstated, so the backend must tolerate both."""
    from alpasim_carla.world import CarlaBackend

    backend = CarlaBackend.__new__(CarlaBackend)
    backend._carla = pytest.importorskip("carla")
    backend._weather_supported = True
    backend._apply_weather(world)  # must not raise either way


# -- end-to-end ---------------------------------------------------------------


def test_render_returns_a_decodable_frame_at_the_requested_size(client, catalog):
    """The whole path: connect, load, spawn, tick, capture, encode."""
    import io

    from PIL import Image

    from alpasim_carla._proto.alpasim_grpc.v0 import sensorsim_pb2
    from alpasim_carla.server import ServerOptions
    from alpasim_carla.world import CarlaBackend

    scenes = load_scene_dir("scenes/examples")
    scene = next(iter(scenes.values()))
    scene.carla_map = MAP

    backend = CarlaBackend(
        host=HOST,
        port=PORT,
        options=ServerOptions(allow_pinhole_approximation=True),
        expect_version=EXPECT_VERSION or scene.carla_version,
        catalog=catalog,
    )
    try:
        request = sensorsim_pb2.RGBRenderRequest(
            scene_id=scene.scene_id,
            resolution_w=640,
            resolution_h=360,
            image_format=sensorsim_pb2.ImageFormat.PNG,
        )
        request.camera_intrinsics.CopyFrom(scene.cameras[0].spec)
        request.sensor_pose.start_pose.quat.w = 1.0
        request.sensor_pose.start_pose.vec.z = 2.0

        image = Image.open(io.BytesIO(backend.render_rgb(request, scene)))
        assert image.size == (640, 360)
    finally:
        backend.close()
