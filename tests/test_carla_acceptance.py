"""Acceptance tests for this branch, against a live CARLA server.

These are the day-one checks. They are the branch's acceptance criteria: the
0.10 port is not done until they pass against
``ghcr.io/abhisheksimforgeai/carla-rfs-munich-belmont:0.10.0``. Every one of
them is currently unverified - no 0.10 server was reachable when the branch
was written.

All are marked ``carla``, so the simulator-free suite is unaffected::

    pytest tests/ -m "not carla"     # simulator-free, runs anywhere
    pytest tests/ -m carla           # needs a server

Configure via environment:

    CARLA_HOST                 default 127.0.0.1
    CARLA_PORT                 default 2000
    CARLA_MAP                  default Town10HD_Opt - the map to expect
    CARLA_EXPECT_VERSION       default 0.10.0 - prefix match
    ALPASIM_BLUEPRINT_CATALOG  listing from tools/list_blueprints.py;
                               when unset the curated 0.9.16 table is used
                               and the catalogue-agreement test is skipped
"""

import os

import pytest

from alpasim_carla.catalog import default_catalog, load_catalog
from alpasim_carla.compat import check_server, map_names_match, normalize_map_name
from alpasim_carla.registry import choose_blueprint
from alpasim_carla.scenes import load_scene_dir

pytestmark = pytest.mark.carla

HOST = os.environ.get("CARLA_HOST", "127.0.0.1")
PORT = int(os.environ.get("CARLA_PORT", "2000"))
MAP = os.environ.get("CARLA_MAP", "Town10HD_Opt")
EXPECT_VERSION = os.environ.get("CARLA_EXPECT_VERSION", "0.10.0")
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


def test_server_reports_the_version_this_branch_targets(client):
    check_server(
        server_version=client.get_server_version(),
        server_map="",
        expected_version=EXPECT_VERSION,
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


def test_map_name_survives_a_reload_unchanged(client):
    """A reload must land on the same normalized name, or _ensure_scene will
    reload on every single request (30 s or more each on UE5)."""
    before = client.get_world().get_map().name
    after = client.load_world(MAP).get_map().name
    assert normalize_map_name(before) == normalize_map_name(after)


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
    """Gate G2's check: a run where NPCs became boxes scores nothing."""
    degraded = []
    for scene in load_scene_dir(scenes_dir).values():
        for track_id, actor_def in scene.actors.items():
            choice = choose_blueprint(track_id, actor_def, scene, catalog)
            if choice.is_fallback:
                degraded.append(
                    f"{scene.scene_id}/{track_id} label={actor_def.label!r} "
                    f"-> {choice.blueprint_id} ({choice.decision})"
                )
    assert not degraded, "actors degraded to the terminal prop:\n" + "\n".join(
        degraded
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


def test_render_returns_a_decodable_frame_at_the_requested_size(catalog):
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
        expect_version=EXPECT_VERSION or None,
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
