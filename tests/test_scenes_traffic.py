"""The scene manifest says what was on the road, and is held to it.

Pure (gate G1). `traffic:` is the scene's half of simforge-closed-loop's run
manifest field of the same name and the same three words. The run manifest
derives its value from the experiment config - from the run's INTENT - and
this repository is the only process that sees the actors actually arrive, so
this is where a suppressed run can be checked rather than asserted.
"""

from pathlib import Path

import pytest

from alpasim_carla.registry import ActorRegistry
from alpasim_carla.scenes import (
    TRAFFIC_SOURCES,
    SceneManifest,
    TrafficContradiction,
    load_scene_dir,
    manifest_from_yaml,
    manifest_to_yaml,
)

REPO = Path(__file__).resolve().parent.parent
SCENE_ID = "clipgt-01d503d4-449b-46fc-8d78-9085e70d3554"

BASE = "scene_id: s\ncarla_map: Town10HD_Opt\ncarla_version: '0.10.0'\n"


def test_the_vocabulary_is_the_run_manifests_vocabulary():
    """Copied verbatim from simforge-closed-loop tools/run_manifest.py, in
    that order. Two documents describing one run, one word for one thing."""
    assert TRAFFIC_SOURCES == (
        "clip_replay",
        "clip_replay_suppressed",
        "scripted",
    )


def test_a_manifest_without_traffic_is_refused_at_load():
    with pytest.raises(ValueError) as exc:
        manifest_from_yaml(BASE)
    message = str(exc.value)
    assert "traffic" in message
    assert "clip_replay_suppressed" in message, (
        "the refusal must name the vocabulary, or the next reader invents a "
        "word and the two documents stop agreeing"
    )


def test_a_word_outside_the_vocabulary_is_refused():
    """`none` and `suppressed` are the two a reasonable person reaches for,
    and neither is what the run manifest will say."""
    for word in ("none", "suppressed", "disabled", "true"):
        with pytest.raises(ValueError, match="run_manifest"):
            manifest_from_yaml(BASE + f"traffic: {word}\n")


def test_an_empty_traffic_is_refused_like_an_omission():
    with pytest.raises(ValueError, match="traffic"):
        manifest_from_yaml(BASE + 'traffic: ""\n')


@pytest.mark.parametrize("word", TRAFFIC_SOURCES)
def test_every_word_in_the_vocabulary_round_trips(word):
    manifest = SceneManifest(
        scene_id="s", carla_map="Town10HD_Opt", carla_version="0.10.0", traffic=word
    )
    assert manifest_from_yaml(manifest_to_yaml(manifest)).traffic == word


def test_a_manifest_is_constructible_in_memory_without_it():
    """The same asymmetry carla_version has, for the same reason: a file is
    what a run is recorded from, and dozens of tests build a manifest that
    has no file behind it."""
    assert SceneManifest(scene_id="s", carla_map="Town10HD_Opt").traffic is None


# -- the shipped manifests ----------------------------------------------------


def test_belmont_declares_the_rerun_contains_none_of_the_clips_traffic():
    scene = load_scene_dir(str(REPO / "scenes" / "belmont"))[SCENE_ID]
    assert scene.traffic == "clip_replay_suppressed"
    assert scene.actors, (
        "the actor table stays: it says what the clip HAD, and the ladder "
        "needs it the moment traffic comes back. `traffic:` says what the "
        "RUN contains. Conflating them is what makes a suppressed run "
        "indistinguishable from a run whose actors were lost to a defect."
    )


def test_g3_declares_the_rehearsal_carried_the_clips_traffic():
    scene = load_scene_dir(str(REPO / "scenes" / "g3"))[SCENE_ID]
    assert scene.traffic == "clip_replay"


def test_the_two_anchorings_of_one_clip_differ_only_in_town_and_traffic():
    belmont = load_scene_dir(str(REPO / "scenes" / "belmont"))[SCENE_ID]
    g3 = load_scene_dir(str(REPO / "scenes" / "g3"))[SCENE_ID]
    assert belmont.scene_id == g3.scene_id
    assert belmont.traffic != g3.traffic


def test_every_shipped_example_declares_its_traffic():
    for scene in load_scene_dir(str(REPO / "scenes" / "examples")).values():
        assert scene.traffic == "scripted"


# -- the check the field gates ------------------------------------------------


class FakeObject:
    def __init__(self, track_id):
        self.track_id = track_id


def _registry(traffic):
    scene = SceneManifest(
        scene_id="s", carla_map="Town10HD_Opt", carla_version="0.10.0", traffic=traffic
    )
    # catalog=None would call default_catalog(), which refuses by design; the
    # check under test runs before anything touches the catalogue, and this
    # registry never gets as far as a spawn.
    registry = ActorRegistry.__new__(ActorRegistry)
    registry._scene = scene
    registry._actors = {}
    return registry


def test_a_suppressed_scene_refuses_a_request_that_carries_traffic():
    """The failure this catches: SimulationConfig.replayed_traffic silently
    not in effect. Both records would still say the road was empty."""
    with pytest.raises(TrafficContradiction) as exc:
        _registry("clip_replay_suppressed").sync([FakeObject("18")])
    message = str(exc.value)
    assert "replayed_traffic" in message
    assert "1 dynamic object" in message


def test_a_suppressed_scene_accepts_an_empty_request():
    _registry("clip_replay_suppressed").sync([])


def test_a_clip_replay_scene_is_not_checked_in_the_other_direction():
    """An empty frame on a replay scene is not an error: actors come and go
    within a rollout, so "none this frame" says nothing. Only the claim that
    can be falsified by one observation is checked."""
    _registry("clip_replay").sync([])


def test_a_manifest_that_never_declared_traffic_is_not_checked():
    """In-memory manifests (tests, scene-from-asl before it is written out)
    carry None. They are also the only ones that can: a manifest on disk is
    refused without the field, which is what keeps this from being an
    opt-out."""
    _registry(None).sync([])
