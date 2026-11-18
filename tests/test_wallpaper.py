"""wallpaper.py: the pattern choice, the dim level and the imported picture."""

import json

import pytest

import config
import storage
import wallpaper
from conftest import JPG, PNG, WEBP


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


# --- Importing a picture ------------------------------------------------------

@pytest.mark.parametrize(("data", "extension"), [(PNG, ".png"), (JPG, ".jpg"), (WEBP, ".webp")])
def test_each_format_is_copied_into_the_data_folder(data, extension):
    choice = wallpaper.import_picture(data)
    copy = config.WALLPAPER_DIR / choice["picture"]
    assert choice["pattern"] == wallpaper.PICTURE
    assert copy.suffix == extension and copy.read_bytes() == data
    assert wallpaper.current() == choice  # and it's remembered


@pytest.mark.parametrize("data", [b"just some text, named photo.png", b"", b"GIF89a" + b"x" * 20])
def test_anything_else_is_refused(data):
    with pytest.raises(wallpaper.WallpaperError):
        wallpaper.import_picture(data)
    assert wallpaper.current()["picture"] is None


def test_pictures_over_the_limit_are_refused(monkeypatch):
    monkeypatch.setattr(config, "WALLPAPER_MAX_MB", 50 / 2**20)  # 50 bytes
    with pytest.raises(wallpaper.WallpaperError) as refused:
        wallpaper.import_picture(PNG)
    assert refused.value.title == "That picture is too big"


def test_a_new_picture_replaces_the_old_copy():
    first = wallpaper.import_picture(PNG)["picture"]
    second = wallpaper.import_picture(JPG)["picture"]
    assert first != second
    assert [path.name for path in config.WALLPAPER_DIR.iterdir()] == [second]


def test_importing_the_same_picture_twice_keeps_it():
    name = wallpaper.import_picture(PNG)["picture"]
    assert wallpaper.import_picture(PNG)["picture"] == name
    assert (config.WALLPAPER_DIR / name).is_file()


def test_switching_to_a_pattern_keeps_the_picture_for_later():
    name = wallpaper.import_picture(PNG)["picture"]
    wallpaper.choose("dots")
    assert wallpaper.current() == {"pattern": "dots", "dim": config.DEFAULT_WALLPAPER_DIM, "picture": name}
    assert wallpaper.choose(wallpaper.PICTURE)["pattern"] == wallpaper.PICTURE


def test_reset_deletes_the_copy_and_any_leftovers():
    wallpaper.import_picture(PNG)
    (config.WALLPAPER_DIR / "wallpaper-halfway.jpg.part").write_bytes(b"...")
    (config.WALLPAPER_DIR / "notes.txt").write_text("not ours, so left alone")
    wallpaper.reset()
    assert [path.name for path in config.WALLPAPER_DIR.iterdir()] == ["notes.txt"]
    assert wallpaper.current()["picture"] is None
