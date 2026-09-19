"""Server-compatibility helpers: map-name matching and the version handshake.

Pure functions (gate G1) - no CARLA, no network. These decide whether the
bridge will talk to the server it found, so they are the one place where a
wrong answer is silent: a map mismatch either reloads every session or
renders the wrong town with no error.
"""

import pytest

from alpasim_carla.compat import (
    ServerMismatch,
    check_server,
    map_names_match,
    normalize_map_name,
    resolve_expected_version,
)


# -- map-name matching --------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Town10HD_Opt", "town10hd"),
        ("Carla/Maps/Town10HD_Opt", "town10hd"),
        ("/Game/Carla/Maps/Town10HD_Opt", "town10hd"),
        ("/Game/Carla/Maps/Town10HD", "town10hd"),
        ("Munich_Belmont", "munich_belmont"),
    ],
)
def test_normalize_strips_path_opt_suffix_and_case(raw, expected):
    assert normalize_map_name(raw) == expected


def test_server_path_matches_bare_manifest_name():
    assert map_names_match("Carla/Maps/Town10HD_Opt", "Town10HD_Opt")


def test_opt_suffix_is_ignored_in_either_direction():
    assert map_names_match("/Game/Carla/Maps/Town10HD_Opt", "Town10HD")
    assert map_names_match("Town10HD", "Town10HD_Opt")


def test_different_towns_do_not_match():
    assert not map_names_match("Carla/Maps/Town10HD_Opt", "Town03")


def test_manifest_name_that_is_only_a_suffix_of_the_server_map_does_not_match():
    """The endswith() compare this replaces matched these; an exact basename
    compare must not. A manifest saying Belmont against a server serving
    Munich_Belmont is a wrong-map bug, not a hit."""
    assert not map_names_match("Carla/Maps/Munich_Belmont", "Belmont")


# -- version handshake --------------------------------------------------------


def test_matching_version_and_map_pass():
    check_server(
        server_version="0.10.0",
        server_map="/Game/Carla/Maps/Town10HD_Opt",
        expected_version="0.10.0",
        expected_map="Town10HD_Opt",
    )


def test_version_mismatch_raises_naming_both_sides():
    with pytest.raises(ServerMismatch) as exc:
        check_server(
            server_version="0.9.16",
            server_map="Town10HD_Opt",
            expected_version="0.10.0",
            expected_map="Town10HD_Opt",
        )
    assert "0.9.16" in str(exc.value)
    assert "0.10.0" in str(exc.value)


def test_map_mismatch_raises_naming_both_sides():
    with pytest.raises(ServerMismatch) as exc:
        check_server(
            server_version="0.10.0",
            server_map="Carla/Maps/Munich_Belmont",
            expected_version="0.10.0",
            expected_map="Belmont",
        )
    assert "Munich_Belmont" in str(exc.value)
    assert "Belmont" in str(exc.value)


def test_expected_version_none_skips_the_version_check():
    check_server(
        server_version="some-git-hash",
        server_map="Town10HD_Opt",
        expected_version=None,
        expected_map="Town10HD_Opt",
    )


def test_expected_map_none_skips_the_map_check():
    check_server(
        server_version="0.10.0",
        server_map="whatever",
        expected_version="0.10.0",
        expected_map=None,
    )


def test_version_compare_is_a_prefix_match_so_build_suffixes_pass():
    """Servers report strings like '0.10.0-dirty' or '0.10.0+ue5'; the pin is
    the release, not the build."""
    check_server(
        server_version="0.10.0-dirty",
        server_map="Town10HD_Opt",
        expected_version="0.10.0",
        expected_map="Town10HD_Opt",
    )


# -- where the expected version comes from ------------------------------------


class _Manifest:
    """Stand-in for SceneManifest: resolve_expected_version only reads
    scene_id and carla_version."""

    def __init__(self, scene_id, carla_version=None):
        self.scene_id = scene_id
        self.carla_version = carla_version


def test_flag_overrides_the_manifest():
    scenes = {"a": _Manifest("a", "0.9.16")}
    assert resolve_expected_version(scenes, flag="0.10.0") == "0.10.0"


def test_manifest_supplies_the_version_when_no_flag_is_given():
    scenes = {"a": _Manifest("a", "0.10.0")}
    assert resolve_expected_version(scenes, flag=None) == "0.10.0"


def test_empty_flag_explicitly_disables_the_check():
    scenes = {"a": _Manifest("a", "0.10.0")}
    assert resolve_expected_version(scenes, flag="") is None


def test_no_flag_and_no_manifest_field_means_no_check():
    scenes = {"a": _Manifest("a", None)}
    assert resolve_expected_version(scenes, flag=None) is None


def test_manifests_agreeing_on_a_version_resolve_to_it():
    scenes = {"a": _Manifest("a", "0.10.0"), "b": _Manifest("b", "0.10.0")}
    assert resolve_expected_version(scenes, flag=None) == "0.10.0"


def test_manifests_disagreeing_is_an_error_naming_both_scenes():
    scenes = {"a": _Manifest("a", "0.9.16"), "b": _Manifest("b", "0.10.0")}
    with pytest.raises(ServerMismatch) as exc:
        resolve_expected_version(scenes, flag=None)
    assert "a" in str(exc.value) and "b" in str(exc.value)


def test_a_manifest_without_the_field_does_not_veto_one_that_has_it():
    scenes = {"a": _Manifest("a", None), "b": _Manifest("b", "0.10.0")}
    assert resolve_expected_version(scenes, flag=None) == "0.10.0"


# -- git-hash servers get a specific message ----------------------------------


def test_a_git_hash_server_is_rejected_with_manifest_advice():
    """The G3 evidence server reported 'fa7751a'. Refusing it is correct; the
    message must say how to accept it deliberately."""
    with pytest.raises(ServerMismatch) as exc:
        check_server(
            server_version="fa7751a",
            server_map="Town10HD_Opt",
            expected_version="0.10.0",
            expected_map="Town10HD_Opt",
        )
    message = str(exc.value)
    assert "git hash" in message
    assert "carla_version" in message


def test_a_release_mismatch_does_not_mention_git_hashes():
    with pytest.raises(ServerMismatch) as exc:
        check_server(
            server_version="0.9.16",
            server_map="Town10HD_Opt",
            expected_version="0.10.0",
            expected_map="Town10HD_Opt",
        )
    assert "git hash" not in str(exc.value)


# -- the client wheel against the server --------------------------------------


def test_a_matching_client_wheel_passes():
    from alpasim_carla.compat import check_client

    check_client(client_version="0.10.0", server_version="0.10.0")


def test_a_mismatched_client_wheel_is_refused():
    """CARLA only warns and then connects, which costs a campaign.

    The first Belmont attempt ran a 0.9.16 client against the 0.10 server -
    the renderer was started from a 3.12 venv, because the Belmont image
    ships only a cp310 wheel - and it loaded the map and hung before the
    first policy decision with nothing naming the cause. The scene handshake
    could not catch it: it compares the manifest's `carla_version` to the
    server's, and both said 0.10.0.
    """
    import pytest

    from alpasim_carla.compat import ClientMismatch, check_client

    with pytest.raises(ClientMismatch) as excinfo:
        check_client(client_version="0.9.16", server_version="0.10.0")
    message = str(excinfo.value)
    # Both sides named, so the log says what was found as well as what was
    # wanted - the same courtesy ServerMismatch already extends.
    assert "0.9.16" in message and "0.10.0" in message
    # And the fix, because the wheel is inside the image and its tag decides
    # the interpreter.
    assert "cp310" in message


def test_the_client_check_is_exact_and_not_by_major_minor():
    """A renderer is the wrong place to be generous.

    The wheel is pinned by the server image it was copied out of, so an
    exact match is always achievable and an inexact one is always a mistake.
    """
    import pytest

    from alpasim_carla.compat import ClientMismatch, check_client

    with pytest.raises(ClientMismatch):
        check_client(client_version="0.9.15", server_version="0.9.16")
