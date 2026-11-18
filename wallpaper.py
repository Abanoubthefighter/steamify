"""The desktop wallpaper: a built-in pattern, or a picture the user imported.

The choice is one small JSON value in the settings table, so it survives a
restart. An imported picture is copied into config.WALLPAPER_DIR, inside the
app's data folder. The installed app can always write there, and the copy
keeps working if the original file is moved or deleted.
"""

import hashlib
import json
import os
import sqlite3

import config
import storage

SETTING = "wallpaper"
PICTURE = "picture"     # the "pattern" that means: show the imported picture
FILE_PREFIX = "wallpaper-"

# How each accepted format starts. Checking the bytes, not the file name,
# means a renamed text file can't sneak in as "photo.png".
FORMATS = {
    ".png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda data: data.startswith(b"\xff\xd8\xff"),
    ".webp": lambda data: data[:4] == b"RIFF" and data[8:12] == b"WEBP",
}


class WallpaperError(Exception):
    """A wallpaper change that can't happen, with a title and message for a popup."""

    def __init__(self, title: str, message: str):
        super().__init__(message)
        self.title = title
        self.message = message

    def as_dict(self) -> dict:
        return {"title": self.title, "message": self.message}


# --- Reading ------------------------------------------------------------------


def current() -> dict:
    """What the wallpaper is now: {"pattern", "dim", "picture"}.

    "picture" is the file name of the imported copy, or None. Anything odd in
    the saved value (an unknown pattern, a copy that went missing) quietly
    falls back to the defaults instead of breaking the page.
    """
    saved = _load()
    picture = saved.get("picture")
    if not (isinstance(picture, str) and _is_our_file(picture) and (config.WALLPAPER_DIR / picture).is_file()):
        picture = None

    pattern = saved.get("pattern")
    if pattern not in config.WALLPAPER_PATTERNS and not (pattern == PICTURE and picture):
        pattern = config.DEFAULT_WALLPAPER

    return {"pattern": pattern, "dim": clamp_dim(saved.get("dim")), "picture": picture}


def clamp_dim(value) -> int:
    """A dim level as a whole percent between 0 and config.WALLPAPER_DIM_MAX."""
    try:
        percent = round(float(value))
    except (TypeError, ValueError):
        return config.DEFAULT_WALLPAPER_DIM
    return max(0, min(config.WALLPAPER_DIM_MAX, percent))


def _load() -> dict:
    try:
        saved = json.loads(storage.get_setting(SETTING) or "{}")
    except (ValueError, sqlite3.Error):
        return {}  # even the error page draws a wallpaper, so this must never fail
    return saved if isinstance(saved, dict) else {}


def _save(choice: dict) -> dict:
    storage.set_setting(SETTING, json.dumps(choice))
    return choice


def _is_our_file(name: str) -> bool:
    """True for names this module makes, like wallpaper-1a2b3c4d5e.png. Nothing else is ever served."""
    stem, _, extension = name.rpartition(".")
    return stem.startswith(FILE_PREFIX) and f".{extension}" in FORMATS and not any(c in name for c in "/\\")


# --- Changing -----------------------------------------------------------------


def choose(pattern: str) -> dict:
    """Switch to a built-in pattern, or back to the imported picture."""
    choice = current()
    if pattern == PICTURE and choice["picture"] is None:
        raise WallpaperError("No picture yet", "Import a picture first, then you can pick it here.")
    if pattern != PICTURE and pattern not in config.WALLPAPER_PATTERNS:
        raise WallpaperError("Unknown wallpaper", "That pattern isn't one of the built-in ones.")
    return _save({**choice, "pattern": pattern})


def set_dim(percent) -> dict:
    """Change how much the picture is darkened."""
    return _save({**current(), "dim": clamp_dim(percent)})


def reset() -> dict:
    """Back to the default pattern and dim level, and delete the imported copy."""
    _delete_pictures(keep=None)
    storage.set_setting(SETTING, None)
    return current()


def _delete_pictures(keep: str | None) -> None:
    """Remove every copy this module made except `keep`, plus any half-written leftovers."""
    if not config.WALLPAPER_DIR.is_dir():
        return
    for path in config.WALLPAPER_DIR.glob(f"{FILE_PREFIX}*"):
        if path.name != keep:
            path.unlink(missing_ok=True)
