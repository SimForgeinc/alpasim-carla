"""The scene manifest declares which CARLA build it was recorded against.

Pure (gate G1). The expected server version is a property of the scene, not
of the process: a 0.9.16 twin scene and the Belmont 0.10 scene cannot be
served by one bridge, and the manifest is where that is written down.
"""

from alpasim_carla.scenes import SceneManifest, manifest_from_yaml, manifest_to_yaml


def test_carla_version_defaults_to_none_so_existing_manifests_still_load():
    manifest = manifest_from_yaml("scene_id: s\ncarla_map: Town10HD_Opt\n")
    assert manifest.carla_version is None


def test_carla_version_round_trips_through_yaml():
    original = SceneManifest(
        scene_id="s", carla_map="Town10HD_Opt", carla_version="0.10.0"
    )
    assert manifest_from_yaml(manifest_to_yaml(original)).carla_version == "0.10.0"


def test_a_manifest_without_the_field_omits_it_rather_than_writing_null():
    text = manifest_to_yaml(SceneManifest(scene_id="s", carla_map="Town10HD_Opt"))
    assert "carla_version" not in text


def test_the_field_is_read_from_hand_written_yaml():
    manifest = manifest_from_yaml(
        "scene_id: s\ncarla_map: Munich_Belmont\ncarla_version: '0.10.0'\n"
    )
    assert manifest.carla_version == "0.10.0"
