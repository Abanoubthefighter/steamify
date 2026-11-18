"""background.py: which players get synced on a timer, with Steam faked."""

import threading

import pytest

import api
import background
import config
import demo
import preferences
import storage
from conftest import make_game, make_profile

ME, FRIEND = "76561198000000001", "76561198000000002"
HOUR = 3600
NOW = 1_800_000_000


@pytest.fixture
def steam(monkeypatch):
    """A pretend Steam that knows two players. Returns the IDs whose library was asked for."""
    asked = []
    monkeypatch.setattr(api, "resolve_steam_id", lambda text: text)
    monkeypatch.setattr(api, "get_player", lambda steam_id: make_profile(steam_id))
    monkeypatch.setattr(api, "get_level", lambda steam_id: 3)
    monkeypatch.setattr(api, "get_owned_games", lambda steam_id: asked.append(steam_id) or [make_game(1, "Hades", hours=2)])
    monkeypatch.setattr(api, "get_achievements", lambda steam_id, app_id: [])
    return asked


def saved(steam_id, hours_ago):
    """A player whose last scan was this many hours before NOW."""
    storage.save_snapshot(make_profile(steam_id), [make_game(1, "Hades", hours=1)], now=NOW - hours_ago * HOUR)


def test_only_players_whose_last_scan_is_old_enough_are_synced(steam):
    saved(ME, hours_ago=3)
    saved(FRIEND, hours_ago=0.2)
    result = background.sync_round(now=NOW)
    assert steam == [ME]
    assert result == {"at": NOW, "synced": 1, "failed": 0, "problem": None}
    assert background.last_round() == result


def test_the_demo_players_are_left_alone(steam):
    demo.install(force=True)
    assert background.players_due(NOW + 400 * 24 * HOUR) == []
    assert background.sync_round(everyone=True, now=NOW) is None


def test_nothing_happens_without_a_key_or_when_switched_off(steam, monkeypatch):
    saved(ME, hours_ago=3)
    preferences.update(background_sync=False)
    assert background.sync_round(now=NOW) is None
    preferences.update(background_sync=True)
    monkeypatch.setattr(config, "STEAM_API_KEY", "")
    assert background.sync_round(now=NOW) is None
    assert steam == []


def test_sync_now_does_everyone_even_when_switched_off(steam):
    saved(ME, hours_ago=3)
    saved(FRIEND, hours_ago=0.2)
    preferences.update(background_sync=False)
    background.sync_round(everyone=True, now=NOW)
    assert sorted(steam) == [ME, FRIEND]


def test_a_player_who_failed_waits_a_whole_interval(steam, monkeypatch):
    saved(ME, hours_ago=3)

    def private(steam_id):
        raise api.PrivateProfile()

    monkeypatch.setattr(api, "get_owned_games", private)
    failed_at = {}
    result = background.sync_round(failed_at=failed_at, now=NOW)
    assert result["failed"] == 1 and result["problem"] == api.PrivateProfile.title
    assert background.sync_round(failed_at=failed_at, now=NOW + 5 * 60) is None  # not again after 5 minutes
    assert background.sync_round(failed_at=failed_at, now=NOW + config.BACKGROUND_SYNC_MINUTES * 60)["failed"] == 1


def test_last_round_ignores_junk():
    storage.set_setting(background.LAST_RUN, "not json")
    assert background.last_round() is None


def test_sync_now_wakes_the_thread_for_a_round_with_everyone(monkeypatch):
    rounds = []
    done = threading.Event()

    def fake_round(everyone=False, failed_at=None, now=None):
        rounds.append(everyone)
        done.set()

    monkeypatch.setattr(background, "sync_round", fake_round)
    monkeypatch.setattr(config, "BACKGROUND_CHECK_MINUTES", 60)  # the timer alone wouldn't fire during the test
    syncing = background.BackgroundSync()
    syncing.start()
    syncing.sync_now()
    assert done.wait(timeout=5)
    assert rounds == [True]
