"""The app's own settings: the ones settings.exe changes.

Like the wallpaper, they're one small JSON value in the settings table, so
they survive a restart. Anything missing or odd in it falls back to the
defaults from config.py, so a broken value can't stop the app from starting.
"""

import json

import config
import storage

SETTING = "preferences"
NOTICE_SHOWN = "tray_notice_shown"  # set once the "still running" notice has been shown


def defaults() -> dict:
    return {
        "keep_running": config.KEEP_RUNNING_DEFAULT,
        "background_sync": config.BACKGROUND_SYNC_DEFAULT,
    }


def current() -> dict:
    """Every setting, saved value or default: {"keep_running": True, "background_sync": True}."""
    saved = _load()
    return {key: saved[key] if isinstance(saved.get(key), bool) else default for key, default in defaults().items()}


def update(**changes: bool) -> dict:
    """Change some settings and save them. Returns all of them.

    Raises ValueError for a name that isn't a setting or a value that isn't
    True or False, so a bad request can't save junk.
    """
    settings = current()
    for key, value in changes.items():
        if key not in settings or not isinstance(value, bool):
            raise ValueError(f"Can't set {key!r} to {value!r}")
        settings[key] = value
    storage.set_setting(SETTING, json.dumps(settings))
    return settings


def keep_running() -> bool:
    """True if closing the window should only hide it to the tray."""
    return current()["keep_running"]


def background_sync() -> bool:
    """True if the app should sync saved players on its own while it's open."""
    return current()["background_sync"]


def first_time_hidden() -> bool:
    """True the very first time the window hides to the tray, then never again."""
    if storage.get_setting(NOTICE_SHOWN):
        return False
    storage.set_setting(NOTICE_SHOWN, "1")
    return True


def _load() -> dict:
    try:
        saved = json.loads(storage.get_setting(SETTING) or "{}")
    except ValueError:
        return {}
    return saved if isinstance(saved, dict) else {}
