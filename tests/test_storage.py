"""Storage tests. Each one runs against a fresh temp database (see conftest.py)."""

import sqlite3
from datetime import date

import pytest

import storage
from conftest import make_game, make_profile

ME = "76561198000000001"
FRIEND = "76561198000000002"
MONDAY = 1_762_776_000  # 10 Nov 2025, midday UTC
DAY = 86400


def day_of(timestamp):
    return date.fromtimestamp(timestamp).isoformat()


def scan(games, when=MONDAY, steam_id=ME, name="tester"):
    return storage.save_snapshot(make_profile(steam_id, name), games, now=when)


def test_first_scan_saves_the_library_but_logs_nothing():
    gained = scan([make_game(730, "Counter-Strike 2", hours=800), make_game(620, "Portal 2")])
    assert gained == 0
    assert storage.first_log_day(ME) is None
    assert {game["name"] for game in storage.get_library(ME)} == {"Counter-Strike 2", "Portal 2"}


def test_second_scan_logs_only_what_changed():
    scan([make_game(730, "Counter-Strike 2", hours=800), make_game(620, "Portal 2", hours=5)])
    gained = scan(
        [make_game(730, "Counter-Strike 2", hours=803), make_game(620, "Portal 2", hours=5)],
        when=MONDAY + DAY,
    )
    assert gained == 180
    history = storage.get_history(ME, since="2000-01-01", bucket="day")
    assert history == [{"bucket": day_of(MONDAY + DAY), "minutes": 180, "top_game": "Counter-Strike 2"}]


def test_two_scans_on_the_same_day_add_up():
    scan([make_game(730, "Counter-Strike 2", hours=10)])
    scan([make_game(730, "Counter-Strike 2", hours=11)], when=MONDAY + DAY)
    scan([make_game(730, "Counter-Strike 2", hours=13)], when=MONDAY + DAY + 3600)
    history = storage.get_history(ME, since="2000-01-01", bucket="day")
    assert [row["minutes"] for row in history] == [180]


def test_a_game_bought_later_counts_from_zero():
    scan([make_game(730, "Counter-Strike 2", hours=10)])
    gained = scan(
        [make_game(730, "Counter-Strike 2", hours=10), make_game(1145360, "Hades", hours=4)],
        when=MONDAY + DAY,
    )
    assert gained == 240


def test_playtime_going_down_is_ignored():
    scan([make_game(730, "Counter-Strike 2", hours=10)])
    assert scan([make_game(730, "Counter-Strike 2", hours=9)], when=MONDAY + DAY) == 0


def test_removed_games_leave_the_library():
    scan([make_game(730, "Counter-Strike 2", hours=10), make_game(620, "Portal 2", hours=2)])
    scan([make_game(730, "Counter-Strike 2", hours=10)], when=MONDAY + DAY)
    assert [game["name"] for game in storage.get_library(ME)] == ["Counter-Strike 2"]


def test_rescanning_updates_the_profile_but_keeps_first_seen():
    scan([], name="old name")
    scan([], when=MONDAY + DAY, name="new name")
    player = storage.get_player(ME)
    assert player["name"] == "new name"
    assert player["first_seen"] == MONDAY
    assert player["synced_at"] == MONDAY + DAY


def test_monthly_history_adds_up_days_and_names_the_top_game():
    scan([make_game(1, "Hades"), make_game(2, "Celeste")])
    storage.add_history(
        ME,
        [
            ("2025-10-03", 1, 60),
            ("2025-10-20", 2, 200),
            ("2025-10-21", 1, 30),
            ("2025-11-02", 1, 45),
        ],
    )
    assert storage.get_history(ME, since="2025-01-01", bucket="month") == [
        {"bucket": "2025-10", "minutes": 290, "top_game": "Celeste"},
        {"bucket": "2025-11", "minutes": 45, "top_game": "Hades"},
    ]
    assert storage.first_log_day(ME) == "2025-10-03"


def test_history_respects_the_start_date():
    scan([make_game(1, "Hades")])
    storage.add_history(ME, [("2025-10-03", 1, 60), ("2025-11-02", 1, 45)])
    history = storage.get_history(ME, since="2025-11-01", bucket="month")
    assert [row["bucket"] for row in history] == ["2025-11"]


def test_shared_games_are_ranked_by_combined_playtime():
    scan([make_game(1, "Hades", hours=50), make_game(2, "Celeste", hours=5), make_game(3, "Only mine", hours=99)])
    scan(
        [make_game(1, "Hades", hours=10), make_game(2, "Celeste", hours=80), make_game(4, "Only theirs", hours=99)],
        steam_id=FRIEND,
    )
    shared, count = storage.get_shared_games(ME, FRIEND, limit=1)
    assert count == 2
    assert shared[0]["name"] == "Celeste"
    assert (shared[0]["my_minutes"], shared[0]["their_minutes"]) == (300, 4800)


def test_no_shared_games():
    scan([make_game(1, "Hades")])
    scan([make_game(2, "Celeste")], steam_id=FRIEND)
    assert storage.get_shared_games(ME, FRIEND, limit=5) == ([], 0)


def test_forgetting_a_player_takes_their_data_too():
    scan([make_game(1, "Hades", hours=1)])
    scan([make_game(1, "Hades", hours=2)], when=MONDAY + DAY)
    storage.forget_player(ME)
    assert storage.get_player(ME) is None
    assert storage.get_library(ME) == []
    assert storage.first_log_day(ME) is None


def test_a_failed_save_leaves_nothing_behind():
    broken_game = {"app_id": 1, "name": "No minutes field"}
    with pytest.raises(sqlite3.Error):
        scan([broken_game])
    assert storage.get_player(ME) is None


def test_players_are_listed_newest_first():
    scan([], steam_id=ME, name="first")
    scan([], steam_id=FRIEND, name="second", when=MONDAY + DAY)
    assert [player["name"] for player in storage.list_players(limit=5)] == ["second", "first"]


def test_settings_round_trip():
    assert storage.get_setting("last_player") is None
    storage.set_setting("last_player", ME)
    storage.set_setting("last_player", FRIEND)
    assert storage.get_setting("last_player") == FRIEND
