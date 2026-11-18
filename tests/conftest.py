"""Shared test setup.

Every test gets its own empty database in a temp folder and a fake API key,
so nothing here can touch the real data or go online by accident.
"""

import sys
from pathlib import Path

import pytest

# Let the tests import the app's modules (api, stats, ...) from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import config  # noqa: E402
import storage  # noqa: E402

FAKE_KEY = "0123456789ABCDEF0123456789ABCDEF"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(config, "WALLPAPER_DIR", tmp_path / "wallpapers")
    monkeypatch.setattr(config, "STEAM_API_KEY", FAKE_KEY)
    api._resolve_custom_name.cache_clear()
    storage.init_db()


def make_game(app_id, name, hours=0.0, recent_hours=0.0, last_played=None):
    """Build a game dict the way api.get_owned_games would return it."""
    return {
        "app_id": app_id,
        "name": name,
        "icon": None,
        "minutes": int(hours * 60),
        "minutes_2weeks": int(recent_hours * 60),
        "last_played": last_played,
    }


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
