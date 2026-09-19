"""The Belmont anchor is the spawn point it was chosen for.

Pure (gate G1): every number below is inline, and the assertions run the
repository's own conversions rather than a hand-derived sign.

The anchor in ``scenes/belmont/clipgt-01d503d4-belmont.yaml`` was not
authored; it was solved. The clip's t0 pose is EXACTLY identity, so
``apply_anchor``, which composes ``anchor . pose`` in right-handed ENU
*before* the handedness conversion, leaves the anchor as the ego's start pose
in ENU. Crossing to CARLA is then ``carla_transform_tuple(..., axes="flu")``
and nothing else. The test that matters is the forward one: run the manifest's
anchor through both functions and land on Belmont spawn point 56's location
and rotator. Get the sign of y or of yaw wrong and it goes red on a laptop
rather than three seeds later on a GPU.

The G3 test below is what licenses the Belmont one. ``scenes/g3`` anchors the
same clip onto Town10 with numbers nobody in this branch computed; solving the
target that manifest lands on reproduces them bit for bit, so the solver used
for Belmont is the same arithmetic that produced the scene Gate C rehearsed
on.
"""

import math
from pathlib import Path

import pytest

from alpasim_carla import frames
from alpasim_carla.compat import (
    ServerMismatch,
    map_names_match,
    normalize_map_name,
    resolve_expected_version,
)
from alpasim_carla.scenes import load_scene_dir

REPO = Path(__file__).resolve().parent.parent
BELMONT_DIR = REPO / "scenes" / "belmont"
G3_DIR = REPO / "scenes" / "g3"

SCENE_ID = "clipgt-01d503d4-449b-46fc-8d78-9085e70d3554"

#: The clip's first recorded pose, read from
#: ``RolloutMetadata.ego_rig_recorded_ground_truth_trajectory`` in a real
#: rollout.asl: 202 poses, last xyz (73.76, 0.53, -0.30), span 73.8 m
#: essentially straight along local +x, initial heading -0.171 deg. t0 itself
#: is exactly identity, which is why the anchor IS the start pose.
CLIP_T0_POSE = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))

#: Belmont spawn point 56, measured on the live server 2026-09-19: the
#: longest run whose walk ended by drifting (maxdev 5.1 deg over 224.0 m)
#: rather than by turning into a junction. CARLA's own left-handed numbers.
#:
#: z IS THE ROAD SURFACE, 1.6872, AND NOT THE SPAWN POINT'S OWN 5.6872.
#: CARLA lifts spawn points four metres above the road so a physics-enabled
#: vehicle can be placed without interpenetrating it. Nothing in this
#: pipeline is physics-enabled - the runtime dictates every ego pose and the
#: bridge teleports to it - so the lift is not a margin, it is a four-metre
#: error, and the renders it produces look merely high rather than wrong.
#: G3 anchors at Town10's road level for the same reason.
SPAWN_56_LOCATION = (-40.42, 9.05, 1.6872)
SPAWN_56_ROTATOR = (0.0, 90.462, 0.0)  # (pitch, yaw, roll)

#: The Town10 transform ``scenes/g3``'s anchor puts the same clip's t0 on.
G3_TARGET_LOCATION = (-68.72206419479491, 27.959680982947674, -0.11150001287460332)
G3_TARGET_ROTATOR = (0.0, 0.15919798612594604, 0.0)

#: And the anchor that manifest published for it, unchanged since G3 passed.
G3_ANCHOR_TRANSLATION = (-68.72206419479491, -27.959680982947674, -0.11150001287460332)
G3_ANCHOR_YAW_DEG = -0.15919798612594604


def solve_anchor(location, rotator):
    """The CARLA transform a clip with an identity t0 should start at,
    expressed as a manifest ``local_to_world`` (ENU translation + yaw).

    ``alpasim_pose_from_carla`` is the repository's inverse of the handedness
    conversion, so the sign of y and the sign of yaw come from the tested code
    instead of from a derivation in a commit message.
    """
    translation, quat = frames.alpasim_pose_from_carla(location, rotator, axes="flu")
    yaw_deg = math.degrees(2.0 * math.atan2(quat[3], quat[0]))
    return translation, yaw_deg


def place_t0(translation, yaw_deg):
    """Where a manifest anchor puts the clip's t0, in CARLA's frame."""
    return frames.carla_transform_tuple(
        *frames.apply_anchor(translation, yaw_deg, CLIP_T0_POSE), axes="flu"
    )


@pytest.fixture(scope="module")
def belmont():
    return load_scene_dir(str(BELMONT_DIR))[SCENE_ID]


@pytest.fixture(scope="module")
def g3():
    return load_scene_dir(str(G3_DIR))[SCENE_ID]


# -- the arithmetic, validated against G3 before it is trusted on Belmont -----


def test_the_solver_reproduces_the_g3_anchor_from_the_target_it_lands_on(g3):
    """If this fails, no Belmont anchor computed the same way is trustworthy.

    Two halves. The forward half recovers G3's target from its published
    anchor and pins it - including that pitch and roll come out zero, which is
    what a road spawn point looks like and what a botched composition would
    not. The inverse half feeds that target to the solver and demands G3's
    numbers back exactly, not approximately.
    """
    assert g3.anchor_translation == pytest.approx(G3_ANCHOR_TRANSLATION, abs=0.0)
    assert g3.anchor_yaw_deg == G3_ANCHOR_YAW_DEG

    location, rotator = place_t0(g3.anchor_translation, g3.anchor_yaw_deg)
    assert location == pytest.approx(G3_TARGET_LOCATION, abs=1e-12)
    assert rotator == pytest.approx(G3_TARGET_ROTATOR, abs=1e-12)

    translation, yaw_deg = solve_anchor(G3_TARGET_LOCATION, G3_TARGET_ROTATOR)
    assert translation == G3_ANCHOR_TRANSLATION
    assert yaw_deg == G3_ANCHOR_YAW_DEG


def test_the_solver_is_the_inverse_of_the_bridge_s_own_forward_path():
    """Solve Belmont spawn 56 from scratch and land back on it."""
    translation, yaw_deg = solve_anchor(SPAWN_56_LOCATION, SPAWN_56_ROTATOR)
    location, rotator = place_t0(translation, yaw_deg)
    assert location == pytest.approx(SPAWN_56_LOCATION, abs=1e-9)
    assert rotator == pytest.approx(SPAWN_56_ROTATOR, abs=1e-9)


# -- the manifest on disk ----------------------------------------------------


def test_the_belmont_anchor_starts_the_clip_on_spawn_point_56(belmont):
    """The one that must never drift: the file's numbers, not a recomputation.

    The anchor and the spawn point were chosen for each other on 2026-09-19.
    Editing either without the other is the silent failure this pins - it
    would put the ego off the road in a town nobody on this branch can look
    at, and the first symptom would be a wrong-looking render three seeds in.
    """
    location, rotator = place_t0(belmont.anchor_translation, belmont.anchor_yaw_deg)
    assert location == pytest.approx(SPAWN_56_LOCATION, abs=1e-9)
    assert rotator == pytest.approx(SPAWN_56_ROTATOR, abs=1e-9)


def test_the_belmont_manifest_loads_through_the_real_loader(belmont):
    """Not "is well-formed YAML" - `load_scene_dir` built this object, so the
    carla_version requirement, the camera specs and the actor table all
    parsed."""
    assert belmont.carla_map == "Belmont_Office_Park_Belmont_CA"
    assert belmont.carla_version == "0.10.0"
    assert belmont.anchor_translation == (-40.42, -9.05, 1.6872)
    assert belmont.anchor_yaw_deg == -90.462
    assert [c.logical_id for c in belmont.cameras] == [
        "camera_cross_left_120fov",
        "camera_cross_right_120fov",
        "camera_front_tele_30fov",
        "camera_front_wide_120fov",
        "camera_rear_left_70fov",
        "camera_rear_right_70fov",
    ]


def test_belmont_carries_g3_s_rig_and_actor_table_unchanged(belmont, g3):
    """Only the anchoring differs. The rig is the clip's recorded rig and the
    actor table is the clip's; a Belmont-shaped edit to either would mean the
    two manifests had stopped describing one clip."""
    assert [c.logical_id for c in belmont.cameras] == [c.logical_id for c in g3.cameras]
    assert [c.spec.SerializeToString() for c in belmont.cameras] == [
        c.spec.SerializeToString() for c in g3.cameras
    ]
    assert [c.rig_to_camera.SerializeToString() for c in belmont.cameras] == [
        c.rig_to_camera.SerializeToString() for c in g3.cameras
    ]
    assert {k: (a.label, a.size_lwh) for k, a in belmont.actors.items()} == {
        k: (a.label, a.size_lwh) for k, a in g3.actors.items()
    }
    assert belmont.ground_z is g3.ground_z is None
    assert belmont.blueprint_overrides == g3.blueprint_overrides == {}


def test_the_two_manifests_are_one_scene_id_and_two_anchorings(belmont, g3):
    """The runtime resolves this id in AlpaSim's scene catalog and the
    renderer resolves the same string in its --scenes-dir, so both sides must
    name one scene. Which town is a SCENES_DIR choice, and `load_scene_dir`
    refusing a duplicate id is what stops the choice from being made by
    filename sort order."""
    assert belmont.scene_id == g3.scene_id == SCENE_ID
    assert belmont.carla_map != g3.carla_map
    assert belmont.anchor_translation != g3.anchor_translation


def test_g3_stays_the_0_9_16_rehearsal_scene_and_the_two_cannot_share_a_process(g3, belmont):
    """G3 is not migrated to 0.10: it is the scene the twin rehearses on, and
    it was anchored against a 0.9.16 server. Because the versions disagree,
    `resolve_expected_version` refuses rather than picking one - which is also
    why the Belmont scene needed its own file instead of an edit to G3."""
    assert g3.carla_version == "0.9.16"
    with pytest.raises(ServerMismatch, match="disagree about carla_version"):
        resolve_expected_version({"g3": g3, "belmont": belmont}, flag=None)
    assert resolve_expected_version({"belmont": belmont}, flag=None) == "0.10.0"


def test_the_server_s_prefixed_map_name_matches_this_manifest(belmont):
    """The probe recorded the server answering
    'Carla/Maps/Belmont_Office_Park_Belmont_CA'. The prefix is stripped in
    `compat.normalize_map_name`, called by `compat.map_names_match`, which is
    what lets this manifest carry the name a human would type."""
    served = "Carla/Maps/Belmont_Office_Park_Belmont_CA"
    assert map_names_match(served, belmont.carla_map)
    assert normalize_map_name(served) == "belmont_office_park_belmont_ca"
    assert not map_names_match("Carla/Maps/Town10HD_Opt", belmont.carla_map)
