"""wallpaper.py: the pattern choice, the dim level and the imported picture."""

import json

import pytest

import config
import storage
import wallpaper


def test_first_run_gets_the_default_pattern():
    assert wallpaper.current() == {
        "pattern": config.DEFAULT_WALLPAPER,
        "dim": config.DEFAULT_WALLPAPER_DIM,
        "picture": None,
    }


def test_a_chosen_pattern_is_remembered():
    wallpaper.choose("dots")
    # Read straight from the database again, like the app does after a restart.
    assert wallpaper.current()["pattern"] == "dots"


def test_unknown_patterns_are_refused():
    with pytest.raises(wallpaper.WallpaperError):
        wallpaper.choose("rainbow")
    assert wallpaper.current()["pattern"] == config.DEFAULT_WALLPAPER


def test_the_picture_cant_be_picked_before_one_is_imported():
    with pytest.raises(wallpaper.WallpaperError):
        wallpaper.choose(wallpaper.PICTURE)


@pytest.mark.parametrize(
    ("given", "kept"),
    [(45, 45), ("45.4", 45), (-10, 0), (500, config.WALLPAPER_DIM_MAX), ("lots", config.DEFAULT_WALLPAPER_DIM)],
)
def test_dim_is_kept_in_range(given, kept):
    assert wallpaper.set_dim(given)["dim"] == kept


def test_reset_goes_back_to_the_defaults():
    wallpaper.choose("checker")
    wallpaper.set_dim(70)
    assert wallpaper.reset() == wallpaper.current() == {
        "pattern": config.DEFAULT_WALLPAPER,
        "dim": config.DEFAULT_WALLPAPER_DIM,
        "picture": None,
    }


def test_a_broken_saved_value_falls_back_to_the_defaults():
    storage.set_setting(wallpaper.SETTING, "{not json")
    assert wallpaper.current()["pattern"] == config.DEFAULT_WALLPAPER
    storage.set_setting(wallpaper.SETTING, json.dumps(["a", "list"]))
    assert wallpaper.current()["pattern"] == config.DEFAULT_WALLPAPER


def test_a_picture_that_went_missing_falls_back_to_the_default():
    storage.set_setting(wallpaper.SETTING, json.dumps({"pattern": "picture", "picture": "wallpaper-gone.png"}))
    assert wallpaper.current() == {**wallpaper.current(), "pattern": config.DEFAULT_WALLPAPER, "picture": None}


def test_only_names_the_app_made_count_as_pictures():
    config.WALLPAPER_DIR.mkdir(parents=True)
    (config.WALLPAPER_DIR / "secret.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    for name in ("secret.png", "../test.db", "wallpaper-x.exe", "wallpaper-..\\x.png"):
        storage.set_setting(wallpaper.SETTING, json.dumps({"pattern": "picture", "picture": name}))
        assert wallpaper.current()["picture"] is None, name
