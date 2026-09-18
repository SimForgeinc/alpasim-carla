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
