"""The scan pipeline, with the Steam calls swapped for fakes."""

import pytest

import api
import storage
import sync
from conftest import make_achievements, make_game, make_profile

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


# --- Achievements -------------------------------------------------------------


@pytest.fixture
def achievements(steam, monkeypatch):
    """Three games with achievements on top of the steam fixture. Returns (asked, answers, library)."""
    _, library = steam
    library[:] = [
        make_game(10, "Played, has achievements", hours=5, has_stats=True),
        make_game(20, "Played, no achievements", hours=5, has_stats=False),
        make_game(30, "Never played", hours=0, has_stats=True),
        make_game(40, "Played a lot", hours=50, has_stats=True),
    ]
    answers = {10: make_achievements(10, unlocked=3, locked=1), 40: make_achievements(40, unlocked=2)}
    asked = []

    def fake(steam_id, app_id):
        asked.append(app_id)
        answer = answers[app_id]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(api, "get_achievements", fake)
    return asked, answers, library


def test_only_played_games_with_achievements_are_checked(achievements):
    asked, _, _ = achievements
    events = list(sync.scan("tester"))
    assert sorted(asked) == [10, 40]
    assert [event["detail"] for event in events if "detail" in event] == ["1/2", "2/2"]
    assert storage.get_achievement_summary(ME) == {"unlocked": 5, "total": 6, "games": 2, "perfect": 1, "checked": 2}


def test_games_are_only_checked_again_once_they_were_played(achievements):
    asked, _, library = achievements
    list(sync.scan("tester"))
    asked.clear()
    list(sync.scan("tester", force=True))
    assert asked == []  # nothing played since, so nothing to ask
    library[3]["minutes"] += 30
    list(sync.scan("tester", force=True))
    assert asked == [40]


def test_a_game_that_times_out_is_tried_again_next_scan(achievements):
    asked, answers, _ = achievements
    answers[10] = api.SteamTimeout()
    events = list(sync.scan("tester"))
    assert events[-1] == {"steam_id": ME, "gained": 0}  # the scan itself still finishes
    assert storage.get_achievement_summary(ME)["checked"] == 1
    answers[10] = make_achievements(10, unlocked=1)
    asked.clear()
    list(sync.scan("tester", force=True))
    assert asked == [10]


def test_being_told_to_slow_down_stops_the_achievements_but_not_the_scan(achievements, monkeypatch):
    asked, answers, _ = achievements
    monkeypatch.setattr(sync.config, "ACHIEVEMENT_WORKERS", 1)  # one at a time, so the order is fixed
    answers[10] = api.RateLimited()
    answers[40] = api.RateLimited()
    events = list(sync.scan("tester"))
    assert events[-1]["steam_id"] == ME
    assert storage.get_achievement_summary(ME)["checked"] == 0


def test_games_to_check():
    games = [make_game(1, "a", hours=1, has_stats=True), make_game(2, "b", hours=2, has_stats=True)]
    assert sync.games_to_check(games, {1: 60, 2: 60}) == [games[1]]
    assert sync.games_to_check(games, {}) == games
