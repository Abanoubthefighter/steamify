"""Shared test setup.

Every test gets its own empty database in a temp folder, a fake API key and
a pretend registry, so nothing here can touch the real data, go online, or
change what Windows starts at login by accident.
"""

import sys
from pathlib import Path

import pytest

# Let the tests import the app's modules (api, stats, ...) from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import config  # noqa: E402
import startup  # noqa: E402
import storage  # noqa: E402

FAKE_KEY = "0123456789ABCDEF0123456789ABCDEF"

# Just enough of each picture format for wallpaper.py's check: the signature
# the format starts with, plus some bytes.
PNG = b"\x89PNG\r\n\x1a\n" + b"png body" * 10
JPG = b"\xff\xd8\xff\xe0" + b"jpg body" * 10
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"webp body" * 10


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(config, "WALLPAPER_DIR", tmp_path / "wallpapers")
    monkeypatch.setattr(config, "STEAM_API_KEY", FAKE_KEY)
    # No test may reach the real Steam. A test that needs an answer fakes it;
    # anything it forgot to fake fails here, loudly, instead of going online.
    monkeypatch.setattr(api._session, "get", _no_network)
    api._resolve_custom_name.cache_clear()
    # The same for the registry: startup.py only ever sees a pretend one.
    monkeypatch.setattr(startup, "winreg", FakeRegistry())
    storage.init_db()


class FakeRegistry:
    """Just enough of the winreg module for startup.py, kept in a dict."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 0x0002
    REG_SZ = 1

    def __init__(self):
        self.keys = {}  # (root, path) -> {value name: value}

    class Key:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved=0, access=0):
        if (root, path) not in self.keys:
            raise FileNotFoundError(path)
        return self.Key(self.keys[(root, path)])

    def CreateKey(self, root, path):
        return self.Key(self.keys.setdefault((root, path), {}))

    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        key.values[name] = value

    def DeleteValue(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        del key.values[name]


def _no_network(*args, **kwargs):
    raise AssertionError("a test tried to talk to the real Steam; fake that call instead")


def make_game(app_id, name, hours=0.0, recent_hours=0.0, last_played=None, has_stats=False):
    """Build a game dict the way api.get_owned_games would return it."""
    return {
        "app_id": app_id,
        "name": name,
        "icon": None,
        "minutes": int(hours * 60),
        "minutes_2weeks": int(recent_hours * 60),
        "last_played": last_played,
        "has_stats": has_stats,
    }


def make_achievements(app_id, unlocked, locked=0, first_unlock=1_700_000_000):
    """A game's achievements the way api.get_achievements returns them: `unlocked` done, `locked` not."""
    done = [
        {"api_name": f"A{app_id}_{n}", "name": f"Done {n}", "description": "", "achieved": True,
         "unlocked_at": first_unlock + n * 3600}
        for n in range(unlocked)
    ]
    todo = [
        {"api_name": f"B{app_id}_{n}", "name": f"Todo {n}", "description": "", "achieved": False, "unlocked_at": None}
        for n in range(locked)
    ]
    return done + todo


def make_profile(steam_id="76561198000000001", name="tester"):
    """Build a profile dict the way api.get_player would return it."""
    return {
        "steam_id": steam_id,
        "name": name,
        "avatar": None,
        "profile_url": f"https://steamcommunity.com/profiles/{steam_id}",
        "status": "Online",
        "created": 1489500000,
        "is_public": True,
        "level": 12,
    }
