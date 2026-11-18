"""Storage tests. Each one runs against a fresh temp database (see conftest.py)."""

import sqlite3
from datetime import date, datetime

import pytest

import storage
from conftest import make_achievements, make_game, make_profile

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


# --- Achievements -------------------------------------------------------------


def owns(steam_id, *games):
    """Save a player who owns these games."""
    storage.save_snapshot(make_profile(steam_id), list(games))


def test_achievement_summary_counts_only_games_still_owned():
    hades, portal = make_game(1, "Hades", hours=40), make_game(2, "Portal", hours=8)
    owns("me", hades, portal)
    storage.save_achievements("me", 1, 2400, make_achievements(1, unlocked=4, locked=6))
    storage.save_achievements("me", 2, 480, make_achievements(2, unlocked=5))
    assert storage.get_achievement_summary("me") == {"unlocked": 9, "total": 15, "games": 2, "perfect": 1, "checked": 2}
    owns("me", hades)  # Portal was refunded
    assert storage.get_achievement_summary("me") == {"unlocked": 4, "total": 10, "games": 1, "perfect": 0, "checked": 1}


def test_a_game_without_achievements_is_remembered_but_not_counted():
    owns("me", make_game(1, "Garry's Mod", hours=3))
    storage.save_achievements("me", 1, 180, [])
    assert storage.get_checked_minutes("me") == {1: 180}
    assert storage.get_achievement_summary("me") == {"unlocked": 0, "total": 0, "games": 0, "perfect": 0, "checked": 1}


def test_coverage_counts_played_games_still_waiting_for_a_check():
    owns("me", make_game(1, "Hades", hours=40), make_game(2, "Portal", hours=8), make_game(3, "Never played"))
    storage.save_achievements("me", 1, 2400, make_achievements(1, unlocked=4, locked=6))
    assert storage.get_achievement_coverage("me") == {"played": 2, "waiting": 1, "private": False}


def test_private_achievements_are_remembered_until_steam_shares_them_again():
    owns("me", make_game(1, "Hades", hours=40))
    storage.mark_achievements_private("me")
    storage.mark_achievements_private("me")  # noticed again on the next scan: still one row, no error
    assert storage.get_achievement_coverage("me")["private"] is True
    storage.save_achievements("me", 1, 2400, make_achievements(1, unlocked=1))
    assert storage.get_achievement_coverage("me")["private"] is False


def test_a_new_check_replaces_the_old_unlocks_and_keeps_known_icons():
    owns("me", make_game(1, "Hades", hours=40))
    storage.save_achievements("me", 1, 100, make_achievements(1, unlocked=1, locked=2))
    storage.save_achievement_icons(1, {"A1_0": "https://example.test/a.jpg"})
    storage.save_achievements("me", 1, 200, make_achievements(1, unlocked=3))
    recent = storage.get_recent_unlocks("me", 10)
    assert [row["api_name"] for row in recent] == ["A1_2", "A1_1", "A1_0"]  # newest first
    assert recent[-1]["icon"] == "https://example.test/a.jpg" and recent[0]["game"] == "Hades"


def test_unlocks_without_a_date_are_left_out_of_the_latest_list():
    owns("me", make_game(1, "Hades", hours=40))
    achievements = make_achievements(1, unlocked=2)
    achievements[1]["unlocked_at"] = None
    storage.save_achievements("me", 1, 100, achievements)
    assert [row["api_name"] for row in storage.get_recent_unlocks("me", 10)] == ["A1_0"]
    assert storage.get_achievement_summary("me")["unlocked"] == 2  # still counted


def test_nearly_done_lists_games_closest_to_finished():
    owns("me", *(make_game(n, f"Game {n}", hours=5) for n in (1, 2, 3, 4)))
    storage.save_achievements("me", 1, 300, make_achievements(1, unlocked=9, locked=1))   # 90%
    storage.save_achievements("me", 2, 300, make_achievements(2, unlocked=4, locked=1))   # 80%
    storage.save_achievements("me", 3, 300, make_achievements(3, unlocked=3, locked=7))   # 30%, too far
    storage.save_achievements("me", 4, 300, make_achievements(4, unlocked=5))             # done already
    assert [(g["name"], g["unlocked"], g["total"]) for g in storage.get_nearly_done("me", 80, 5)] == [
        ("Game 1", 9, 10), ("Game 2", 4, 5)]


def test_shared_achievements_only_compare_games_both_own():
    owns("me", make_game(1, "Hades", hours=40), make_game(2, "Portal", hours=8))
    owns("you", make_game(1, "Hades", hours=10), make_game(3, "Celeste", hours=8))
    storage.save_achievements("me", 1, 2400, make_achievements(1, unlocked=10))
    storage.save_achievements("me", 2, 480, make_achievements(2, unlocked=5))
    storage.save_achievements("you", 1, 600, make_achievements(1, unlocked=4, locked=6))
    storage.save_achievements("you", 3, 480, make_achievements(3, unlocked=7))
    assert storage.get_shared_achievements("me", "you") == {
        "games": 1, "my_unlocked": 10, "their_unlocked": 4, "my_perfect": 1, "their_perfect": 0}


def test_the_rarest_unlock_and_which_games_need_rarity():
    owns("me", make_game(1, "Hades", hours=40), make_game(2, "Portal", hours=8), make_game(3, "Celeste", hours=1))
    storage.save_achievements("me", 1, 2400, make_achievements(1, unlocked=2))
    storage.save_achievements("me", 2, 480, make_achievements(2, unlocked=1, locked=1))
    storage.save_achievements("me", 3, 60, make_achievements(3, unlocked=0, locked=4))
    assert sorted(storage.games_needing_rarity("me", checked_before=10**10)) == [1, 2]  # Celeste: nothing unlocked
    assert storage.get_rarest_unlock("me") is None

    storage.save_rarity([(1, {"A1_0": 40.0, "A1_1": 2.5}), (2, {"A2_0": 9.0, "B2_0": 0.1})], now=1000)
    rarest = storage.get_rarest_unlock("me")
    assert (rarest["name"], rarest["game"], rarest["percent"]) == ("Done 1", "Hades", 2.5)  # B2_0 is rarer, but locked
    assert storage.games_needing_rarity("me", checked_before=500) == []
    assert sorted(storage.games_needing_rarity("me", checked_before=2000)) == [1, 2]


# --- trophies.exe ---


def test_achievement_games_lists_owned_games_that_have_achievements():
    owns("me", make_game(1, "Hades", hours=40), make_game(2, "Garry's Mod", hours=3), make_game(3, "Portal", hours=8))
    storage.save_achievements("me", 1, 2400, make_achievements(1, unlocked=2, locked=3))
    storage.save_achievements("me", 2, 180, [])  # has none: not listed
    storage.save_achievements("me", 3, 480, make_achievements(3, unlocked=0, locked=4))
    games = {game["name"]: game for game in storage.get_achievement_games("me")}
    assert set(games) == {"Hades", "Portal"}
    assert games["Hades"]["unlocked"] == 2 and games["Hades"]["total"] == 5
    assert games["Hades"]["last_unlock"] == 1_700_000_000 + 3600  # the newer of the two
    assert games["Portal"]["last_unlock"] is None


def test_game_achievements_list_unlocked_newest_first_then_the_most_common_locked_ones():
    owns("me", make_game(1, "Hades", hours=40))
    storage.save_achievements("me", 1, 2400, make_achievements(1, unlocked=2, locked=3))
    storage.save_rarity([(1, {"B1_0": 5.0, "B1_1": 60.0, "B1_2": 0.4})])
    listed = storage.get_game_achievements("me", 1)
    assert [item["api_name"] for item in listed] == ["A1_1", "A1_0", "B1_1", "B1_0", "B1_2"]
    assert [item["achieved"] for item in listed] == [True, True, False, False, False]
    assert listed[2]["unlocked_at"] is None and listed[2]["percent"] == 60.0


def test_game_achievements_are_per_player():
    owns("me", make_game(1, "Hades", hours=40))
    owns("friend", make_game(1, "Hades", hours=10))
    storage.save_achievements("me", 1, 2400, make_achievements(1, unlocked=3))
    storage.save_achievements("friend", 1, 600, make_achievements(1, unlocked=1, locked=2))
    assert sum(item["achieved"] for item in storage.get_game_achievements("friend", 1)) == 1


def test_unlock_counts_by_month_and_year():
    owns("me", make_game(1, "Hades", hours=40))
    achievements = make_achievements(1, unlocked=4)
    for item, when in zip(achievements, ("2025-12-30", "2026-01-02", "2026-01-20", None)):
        item["unlocked_at"] = int(datetime.fromisoformat(f"{when}T12:00").timestamp()) if when else None
    storage.save_achievements("me", 1, 2400, achievements)
    assert storage.get_unlock_counts("me", "month") == [
        {"bucket": "2025-12", "unlocks": 1}, {"bucket": "2026-01", "unlocks": 2},
    ]
    assert storage.get_unlock_counts("me", "year") == [{"bucket": "2025", "unlocks": 1}, {"bucket": "2026", "unlocks": 2}]
    assert storage.get_unlock_counts("me", "month", since="2026-01") == [{"bucket": "2026-01", "unlocks": 2}]


def test_achievements_a_game_no_longer_has_are_dropped():
    owns("me", make_game(1, "Hades", hours=40))
    storage.save_achievements("me", 1, 100, make_achievements(1, unlocked=1, locked=3))
    storage.save_achievements("me", 1, 200, make_achievements(1, unlocked=1, locked=1))  # the game lost two
    assert len(storage.get_game_achievements("me", 1)) == 2
    storage.save_achievements("me", 1, 300, [])  # "no stats" says nothing about the list, so it's kept
    assert len(storage.get_game_achievements("me", 1)) == 2


def test_missing_icons():
    owns("me", make_game(1, "Hades", hours=40))
    storage.save_achievements("me", 1, 100, make_achievements(1, unlocked=2))
    assert storage.is_missing_icons(1)
    storage.save_achievement_icons(1, {"A1_0": "https://example.test/0.jpg", "A1_1": "https://example.test/1.jpg"})
    assert not storage.is_missing_icons(1)
