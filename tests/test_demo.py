"""The made-up player: is the data believable and is it the same every time?"""

from datetime import date, timedelta

import demo
import stats
import storage


def test_install_creates_both_players():
    demo.install()
    assert storage.get_player(demo.PLAYER_ID)["name"] == "player_one"
    assert storage.get_player(demo.FRIEND_ID)["name"] == "player_two"
    assert len(storage.get_library(demo.PLAYER_ID)) == len(demo.FAVOURITES) + len(demo.SHELF)


def test_game_names_are_unique():
    names = [name for name, _ in demo.FAVOURITES] + demo.SHELF
    assert len(names) == len(set(names))


def test_demo_games_use_negative_ids():
    demo.install()
    assert all(game["app_id"] < 0 for game in storage.get_library(demo.PLAYER_ID))


def test_same_seed_same_library():
    demo.install()
    first = sorted(storage.get_library(demo.PLAYER_ID), key=lambda game: game["app_id"])
    demo.install(force=True)
    second = sorted(storage.get_library(demo.PLAYER_ID), key=lambda game: game["app_id"])
    assert [game["minutes"] for game in first] == [game["minutes"] for game in second]


def test_installing_twice_in_a_day_does_nothing(monkeypatch):
    demo.install()
    monkeypatch.setattr(storage, "forget_player", lambda steam_id: 1 / 0)  # would blow up on a rebuild
    demo.install()


def test_history_covers_a_year_and_ends_today():
    demo.install()
    today = date.today()
    assert storage.first_log_day(demo.PLAYER_ID) <= (today - timedelta(days=330)).isoformat()
    last_fortnight = storage.get_history(demo.PLAYER_ID, since=(today - timedelta(days=13)).isoformat(), bucket="day")
    assert last_fortnight, "the demo player should have played something recently"
    assert last_fortnight[-1]["bucket"] <= today.isoformat()


def test_recent_hours_agree_with_the_play_log():
    demo.install()
    summary = stats.summarize(storage.get_library(demo.PLAYER_ID))
    since = (date.today() - timedelta(days=13)).isoformat()
    logged = sum(row["minutes"] for row in storage.get_history(demo.PLAYER_ID, since=since, bucket="day"))
    assert summary["recent_minutes"] == logged


def test_first_scan_is_dated_a_year_back():
    demo.install()
    player = storage.get_player(demo.PLAYER_ID)
    assert player["synced_at"] - player["first_seen"] > 300 * 86400


def test_friend_shares_part_of_the_library():
    demo.install()
    _, shared_count = storage.get_shared_games(demo.PLAYER_ID, demo.FRIEND_ID, limit=3)
    assert 0 < shared_count < len(storage.get_library(demo.PLAYER_ID))


def test_pretend_scan_walks_through_the_same_steps(monkeypatch):
    import sync

    monkeypatch.setattr(demo, "STEP_DELAY", 0)
    events = list(demo.scan(demo.PLAYER_ID))
    assert [event["label"] for event in events[:-1]] == list(sync.STEPS)
    assert events[-1] == {"steam_id": demo.PLAYER_ID, "gained": 0}


def test_demo_players_get_made_up_achievements():
    demo.install(force=True)
    mine = storage.get_achievement_summary(demo.PLAYER_ID)
    assert mine["games"] > 0 and 0 < mine["unlocked"] < mine["total"]
    assert storage.get_recent_unlocks(demo.PLAYER_ID, 3)
    assert storage.get_shared_achievements(demo.PLAYER_ID, demo.FRIEND_ID)["games"] > 0
