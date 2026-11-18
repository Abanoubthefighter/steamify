"""The scan pipeline, with the Steam calls swapped for fakes."""

import threading

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
    monkeypatch.setattr(api, "get_achievements", lambda steam_id, app_id: [])  # unless a test says otherwise
    return calls, library


def test_scan_reports_every_step_then_the_result(steam):
    events = list(sync.scan("tester"))
    assert [event["label"] for event in events[:-1] if "label" in event] == list(sync.STEPS)
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
    answers = {10: make_achievements(10, unlocked=3, locked=1), 20: [], 40: make_achievements(40, unlocked=2)}
    asked = []

    def fake(steam_id, app_id):
        asked.append(app_id)
        answer = answers[app_id]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(api, "get_achievements", fake)
    monkeypatch.setattr(api, "get_global_percentages", lambda app_id: rarity.get(app_id, {}))
    monkeypatch.setattr(api, "get_achievement_icons", lambda app_id: icons_asked.append(app_id) or {})
    return asked, answers, library


rarity = {}       # what the fake Steam says about rarity: {app_id: {api name: percent}}
icons_asked = []  # games the fake Steam was asked for icons


def test_every_played_game_is_checked(achievements):
    asked, _, _ = achievements
    events = list(sync.scan("tester"))
    assert sorted(asked) == [10, 20, 40]  # not 30: never played, so nothing can be unlocked
    progress = [event.get("label") or event.get("detail") for event in events[:-1]]
    assert progress[-7:] == ["Checking achievements", "1/3", "2/3", "3/3", "Checking how rare they are", "1/2", "2/2"]
    assert storage.get_achievement_summary(ME) == {"unlocked": 5, "total": 6, "games": 2, "perfect": 1, "checked": 3}


def test_a_game_steam_does_not_flag_can_still_have_achievements(achievements):
    asked, answers, _ = achievements
    answers[20] = make_achievements(20, unlocked=1, locked=1)  # Steam's has_stats flag was wrong
    list(sync.scan("tester"))
    assert storage.get_achievement_summary(ME)["games"] == 3


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
    assert storage.get_achievement_summary(ME)["checked"] == 2  # 20 and 40, not 10
    answers[10] = make_achievements(10, unlocked=1)
    asked.clear()
    list(sync.scan("tester", force=True))
    assert asked == [10]


@pytest.fixture
def waits(monkeypatch):
    """Record the pauses a scan takes instead of actually sleeping through them."""
    slept = []
    monkeypatch.setattr(sync.time, "sleep", slept.append)
    return slept


def test_being_told_to_slow_down_waits_then_carries_on(achievements, waits, monkeypatch):
    monkeypatch.setattr(sync.config, "ACHIEVEMENT_WORKERS", 1)  # one at a time, so the order is fixed
    answer_normally = api.get_achievements
    told = []

    def slow_down_once(steam_id, app_id):
        if not told:  # the very first call; after the wait Steam is fine again
            told.append(app_id)
            raise api.RateLimited()
        return answer_normally(steam_id, app_id)

    monkeypatch.setattr(api, "get_achievements", slow_down_once)
    events = list(sync.scan("tester"))
    assert waits == [sync.config.SLOW_DOWN_SECONDS]
    assert {"detail": "0/3, Steam asked us to wait"} in events
    assert storage.get_achievement_summary(ME)["checked"] == 3


def test_if_steam_keeps_saying_slow_down_the_rest_wait_for_the_next_scan(achievements, waits):
    asked, answers, _ = achievements
    for app_id in answers:
        answers[app_id] = api.RateLimited()
    events = list(sync.scan("tester"))
    assert events[-1]["steam_id"] == ME  # the scan itself still finishes
    seconds = sync.config.SLOW_DOWN_SECONDS
    assert waits == [seconds * n for n in range(1, sync.config.SLOW_DOWN_RETRIES + 1)]
    assert storage.get_achievement_summary(ME)["checked"] == 0


def test_a_player_who_never_shared_and_refuses_everything_is_private(achievements, waits):
    asked, answers, _ = achievements
    for app_id in answers:
        answers[app_id] = api.PrivateAchievements()
    events = list(sync.scan("tester"))
    assert events[-1]["steam_id"] == ME
    assert waits == []  # no point waiting: Steam won't change its mind in a few seconds
    assert storage.get_achievement_summary(ME)["checked"] == 0  # nothing saved, so the next scan asks again
    assert storage.get_achievement_coverage(ME)["private"] is True


def test_refusing_game_after_game_stops_early(achievements, monkeypatch):
    asked, answers, library = achievements
    monkeypatch.setattr(sync.config, "NOT_PUBLIC_GIVE_UP", 2)
    monkeypatch.setattr(sync.config, "ACHIEVEMENT_WORKERS", 1)
    for app_id in answers:
        answers[app_id] = api.PrivateAchievements()
    list(sync.scan("tester"))
    assert storage.get_achievement_coverage(ME)["private"] is True
    assert len(asked) <= 3  # 2 refusals, plus at most one call already on its way


def test_games_to_check():
    games = [make_game(1, "a", hours=1, has_stats=True), make_game(2, "b", hours=2, has_stats=True)]
    assert sync.games_to_check(games, {1: 60, 2: 60}) == [games[1]]
    assert sync.games_to_check(games, {}) == games


def test_games_steam_flags_are_checked_first():
    games = [make_game(1, "unflagged", hours=1), make_game(2, "flagged", hours=1, has_stats=True), make_game(3, "unflagged too", hours=1)]
    assert [game["app_id"] for game in sync.games_to_check(games, {})] == [2, 1, 3]


def test_rarity_is_fetched_for_games_with_unlocks_then_left_alone_for_a_week(achievements, monkeypatch):
    asked_rarity = []
    monkeypatch.setattr(api, "get_global_percentages", lambda app_id: asked_rarity.append(app_id) or {f"A{app_id}_0": 3.5})
    list(sync.scan("tester"))
    assert sorted(asked_rarity) == [10, 40]
    assert storage.get_rarest_unlock(ME)["percent"] == 3.5

    asked_rarity.clear()
    list(sync.scan("tester", force=True))
    assert asked_rarity == []  # still fresh

    monkeypatch.setattr(sync.config, "RARITY_REFRESH_DAYS", -1)  # as if a week (and then some) went by
    list(sync.scan("tester", force=True))
    assert sorted(asked_rarity) == [10, 40]


def test_icons_are_only_fetched_for_what_achievements_exe_shows(achievements, monkeypatch):
    icons_asked.clear()
    list(sync.scan("tester"))
    assert sorted(set(icons_asked)) == [10, 40]  # the games in the latest-unlocks list
    monkeypatch.setattr(api, "get_achievement_icons", lambda app_id: icons_asked.append(app_id) or {
        f"A{app_id}_{n}": f"https://example.test/{app_id}/{n}.jpg" for n in range(5)})
    list(sync.scan("tester", force=True))
    icons_asked.clear()
    list(sync.scan("tester", force=True))
    assert icons_asked == []  # every shown unlock has its icon now


def test_a_second_scan_waits_for_the_first(steam):
    first = sync.scan("tester")
    assert next(first) == {"label": sync.STEPS[0]}
    next(first)  # holds the lock now, halfway through
    second = sync.scan("tester", force=True)
    assert next(second) == {"label": sync.STEPS[0]}
    finished = []
    waiting = threading.Thread(target=lambda: finished.append(list(second)))
    waiting.start()
    waiting.join(timeout=0.5)
    assert waiting.is_alive()  # stuck behind the first scan
    first.close()  # the page went away: the lock must be let go
    waiting.join(timeout=5)
    assert finished and finished[0][0] == {"detail": "waiting for the scan that's already running"}
    assert finished[0][-1]["steam_id"] == ME


def test_not_public_for_an_unflagged_game_only_means_that_game(achievements):
    asked, answers, _ = achievements
    answers[20] = api.PrivateAchievements()  # game 20 isn't flagged by Steam
    list(sync.scan("tester"))
    assert storage.get_achievement_coverage(ME) == {"played": 3, "waiting": 0, "private": False}
    assert storage.get_achievement_summary(ME)["games"] == 2  # the two real ones still count


def test_what_happened_on_a_real_profile(achievements):
    """Some games shared their achievements, the rest (flagged or not) answered "not public"."""
    asked, answers, library = achievements
    answers[20] = api.PrivateAchievements()
    del answers[40]
    library[:] = library[:3]  # 10 shares, 20 refuses
    list(sync.scan("tester"))
    library.append(make_game(50, "Flagged, refuses", hours=3, has_stats=True))
    answers[50] = api.PrivateAchievements()
    list(sync.scan("tester", force=True))  # only 50 is new: it refuses, nothing else answers
    coverage = storage.get_achievement_coverage(ME)
    assert coverage["private"] is False  # 10 shared before, so the profile isn't private
    assert coverage["waiting"] == 0  # 20 and 50 are noted as checked, nothing to see


def test_a_game_that_refuses_later_keeps_what_it_had(achievements):
    asked, answers, library = achievements
    list(sync.scan("tester"))
    library[0]["minutes"] += 30  # played game 10 since
    answers[10] = api.PrivateAchievements()
    list(sync.scan("tester", force=True))
    assert storage.get_achievement_summary(ME)["unlocked"] == 5  # 10's three unlocks are still there
    assert storage.get_achievement_coverage(ME)["private"] is False
