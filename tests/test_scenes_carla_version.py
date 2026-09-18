"""The scene manifest declares which CARLA build it was recorded against.

Pure (gate G1). The expected server version is a property of the scene, not
of the process: a 0.9.16 twin scene and the Belmont 0.10 scene cannot be
served by one bridge, and the manifest is where that is written down.
"""

import pytest

from alpasim_carla.scenes import SceneManifest, manifest_from_yaml, manifest_to_yaml


def test_a_manifest_without_carla_version_is_refused_at_load():
    """This used to assert the opposite, and the opposite was the defect.

    `compat.py` treats a scene that omits the field as ABSTAINING, so a
    manifest could skip the server handshake by saying nothing. That is an
    opt-in wearing a check's clothes, and it was not hypothetical: the g3
    scene - the only one Stage C loads - omitted it, while all three
    render-test manifests declared theirs. The one that mattered was the one
    running unchecked.
    """
    with pytest.raises(ValueError) as excinfo:
        manifest_from_yaml("scene_id: s\ncarla_map: Town10HD_Opt\n")
    message = str(excinfo.value)
    assert "carla_version" in message
    assert "--expect-carla-version" in message, (
        "the refusal must name the deliberate way to skip the check, or the "
        "next reader adds the field with a guess to make the error go away."
    )


def test_an_empty_carla_version_is_refused_too():
    """`carla_version: ""` is an omission that looks like a declaration."""
    with pytest.raises(ValueError):
        manifest_from_yaml('scene_id: s\ncarla_map: Town10HD_Opt\ncarla_version: ""\n')


def test_carla_version_round_trips_through_yaml():
    original = SceneManifest(
        scene_id="s", carla_map="Town10HD_Opt", carla_version="0.10.0"
    )
    assert manifest_from_yaml(manifest_to_yaml(original)).carla_version == "0.10.0"


def test_a_manifest_without_the_field_omits_it_and_cannot_be_read_back():
    """The serializer still omits a None, and the loader now refuses one.

    That asymmetry is deliberate and worth pinning rather than smoothing:
    `SceneManifest` stays constructible in memory without a version - the
    dataclass default is None and dozens of tests build one - while a
    manifest on DISK must declare it, because a file is what a server gets
    checked against. Writing one and reading it back is the round trip that
    must not silently work.
    """
    text = manifest_to_yaml(SceneManifest(scene_id="s", carla_map="Town10HD_Opt"))
    assert "carla_version" not in text
    with pytest.raises(ValueError, match="carla_version"):
        manifest_from_yaml(text)


def test_the_field_is_read_from_hand_written_yaml():
    manifest = manifest_from_yaml(
        "scene_id: s\ncarla_map: Munich_Belmont\ncarla_version: '0.10.0'\n"
    )
    assert manifest.carla_version == "0.10.0"
