"""The scan pipeline, with the Steam calls swapped for fakes."""

import pytest

import api
import storage
import sync
from conftest import make_game, make_profile

ME = "76561198000000001"


@pytest.fixture
def steam(monkeypatch):
    """A pretend Steam that knows one player. Returns the list of calls made to it."""
    calls = []
    library = [make_game(730, "Counter-Strike 2", hours=10)]

    def record(name, result):
        def fake(*args, **kwargs):
            calls.append(name)
            return result() if callable(result) else result

        return fake

    monkeypatch.setattr(api, "resolve_steam_id", record("resolve", ME))
    monkeypatch.setattr(api, "get_player", record("player", lambda: make_profile(ME)))
    monkeypatch.setattr(api, "get_level", record("level", 12))
    monkeypatch.setattr(api, "get_owned_games", record("games", lambda: [dict(game) for game in library]))
    return calls, library


def test_scan_reports_every_step_then_the_result(steam):
    events = list(sync.scan("tester"))
    assert [event["label"] for event in events[:-1]] == list(sync.STEPS)
    assert events[-1] == {"steam_id": ME, "gained": 0}
    assert storage.get_player(ME)["level"] == 12
    assert len(storage.get_library(ME)) == 1


def test_a_recent_scan_is_not_repeated(steam):
    calls, _ = steam
    list(sync.scan("tester"))
    calls.clear()
    events = list(sync.scan("tester"))
    assert calls == ["resolve"]  # no profile or library request the second time
    assert events[-1] == {"steam_id": ME, "gained": 0}


def test_force_skips_the_shortcut_and_logs_new_playtime(steam):
    calls, library = steam
    list(sync.scan("tester"))
    library[0]["minutes"] += 90
    calls.clear()
    events = list(sync.scan("tester", force=True))
    assert calls == ["resolve", "player", "level", "games"]
    assert events[-1]["gained"] == 90


def test_is_fresh(monkeypatch):
    assert sync.is_fresh(None) is False
    monkeypatch.setattr(sync.time, "time", lambda: 10_000)
    assert sync.is_fresh({"synced_at": 10_000 - 60}) is True
    assert sync.is_fresh({"synced_at": 10_000 - 24 * 3600}) is False


def test_steam_errors_stop_the_scan_before_anything_is_saved(steam, monkeypatch):
    def private(*args):
        raise api.PrivateProfile()

    monkeypatch.setattr(api, "get_owned_games", private)
    with pytest.raises(api.PrivateProfile):
        list(sync.scan("tester"))
    assert storage.get_player(ME) is None
