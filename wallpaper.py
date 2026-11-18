"""The desktop wallpaper: a built-in pattern, or one of the user's pictures.

The choice is one small JSON value in the settings table, so it survives a
restart. Every imported picture is copied into config.WALLPAPER_DIR, inside
the app's data folder. The installed app can always write there, and a copy
keeps working if the original file is moved or deleted. The copies stay
until the user deletes them in wallpaper.exe, so the folder itself is the
list of pictures; nothing else needs to keep track of them.
"""

import hashlib
import json
import os
import sqlite3

import config
import storage

SETTING = "wallpaper"
PICTURE = "picture"     # the "pattern" that means: show one of the imported pictures
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

    "picture" is the file name of the picture last picked, or None. It's
    kept while a built-in pattern is on, so switching back is one click.
    Anything odd in the saved value (an unknown pattern, a picture that was
    deleted) quietly falls back to the defaults instead of breaking the page.
    """
    saved = _load()
    picture = saved.get("picture")
    if not (isinstance(picture, str) and _is_our_file(picture) and (config.WALLPAPER_DIR / picture).is_file()):
        picture = None

    pattern = saved.get("pattern")
    if pattern not in config.WALLPAPER_PATTERNS and not (pattern == PICTURE and picture):
        pattern = config.DEFAULT_WALLPAPER

    return {"pattern": pattern, "dim": clamp_dim(saved.get("dim")), "picture": picture}


def pictures() -> list[str]:
    """The file names of every imported picture, newest first."""
    if not config.WALLPAPER_DIR.is_dir():
        return []
    found = [path for path in config.WALLPAPER_DIR.iterdir() if path.is_file() and _is_our_file(path.name)]
    found.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return [path.name for path in found]


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


def choose(pattern: str, picture: str | None = None) -> dict:
    """Switch to a built-in pattern, or to one of the imported pictures.

    For a picture, `picture` names which one; left out, it's the last one picked.
    """
    choice = current()
    if pattern == PICTURE:
        picture = picture or choice["picture"]
        if picture not in pictures():
            if not pictures():
                raise WallpaperError("No picture yet", "Import a picture first, then you can pick it here.")
            raise WallpaperError("That picture is gone", "It isn't in the app any more. Pick another one.")
        return _save({**choice, "pattern": PICTURE, "picture": picture})
    if pattern not in config.WALLPAPER_PATTERNS:
        raise WallpaperError("Unknown wallpaper", "That pattern isn't one of the built-in ones.")
    return _save({**choice, "pattern": pattern})


def set_dim(percent) -> dict:
    """Change how much the picture is darkened."""
    return _save({**current(), "dim": clamp_dim(percent)})


def import_picture(data: bytes) -> dict:
    """Copy a picture into the app's data folder, add it to the list and show it.

    The copy is named after a short fingerprint of its contents, so a new
    picture always gets a new name. That way the window never shows an old
    copy from its cache, and importing the same picture twice doesn't make
    a duplicate (it just moves back to the top of the list).
    """
    if len(data) > config.WALLPAPER_MAX_MB * 1024 * 1024:
        raise WallpaperError("That picture is too big", f"Pick one under {config.WALLPAPER_MAX_MB} MB.")
    extension = _picture_extension(data)
    name = f"{FILE_PREFIX}{hashlib.sha256(data).hexdigest()[:12]}{extension}"

    folder = config.WALLPAPER_DIR
    folder.mkdir(parents=True, exist_ok=True)
    # Write under a temporary name, then swap it in. If the app is closed
    # halfway, the wallpaper is never a half-written file.
    temporary = folder / f"{name}.part"
    temporary.write_bytes(data)
    os.replace(temporary, folder / name)

    _delete_leftovers()
    return _save({**current(), "pattern": PICTURE, "picture": name})


def _picture_extension(data: bytes) -> str:
    for extension, looks_right in FORMATS.items():
        if looks_right(data):
            return extension
    raise WallpaperError("That's not a picture the app can use", "Pick a PNG, JPG or WebP image.")


def delete_picture(name: str) -> dict:
    """Delete one imported picture. If it was on the desktop, the default wallpaper comes back.

    Only the app's own copy goes; the original file on the user's computer is never touched.
    """
    if name not in pictures():
        raise WallpaperError("That picture is gone", "It was already deleted.")
    (config.WALLPAPER_DIR / name).unlink(missing_ok=True)
    return _save(current())  # current() notices the file is gone and falls back


def reset() -> dict:
    """Back to the default wallpaper and dim level. The imported pictures stay in the list."""
    _delete_leftovers()
    storage.set_setting(SETTING, None)
    return current()


def _delete_leftovers() -> None:
    """Remove half-written copies, left behind if the app was closed in the middle of an import."""
    if config.WALLPAPER_DIR.is_dir():
        for path in config.WALLPAPER_DIR.glob(f"{FILE_PREFIX}*.part"):
            path.unlink(missing_ok=True)
