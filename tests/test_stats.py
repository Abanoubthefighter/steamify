"""Stats tests. Plain lists in, plain numbers out."""

import stats
from conftest import make_game

LIBRARY = [
    make_game(1, "Counter-Strike 2", hours=800, recent_hours=3, last_played=5000),
    make_game(2, "Elden Ring", hours=150, last_played=3000),
    make_game(3, "celeste", hours=50, recent_hours=4, last_played=6000),
    make_game(4, "Hades II"),
    make_game(5, "Among Us"),
]


def names(games):
    return [game["name"] for game in games]


def test_summarize_counts_everything():
    summary = stats.summarize(LIBRARY)
    assert summary["game_count"] == 5
    assert summary["played_count"] == 3
    assert summary["never_count"] == 2
    assert summary["played_percent"] == 60
    assert summary["total_minutes"] == 1000 * 60
    assert summary["recent_minutes"] == 7 * 60
    assert summary["recent_count"] == 2
    assert summary["top_game"]["name"] == "Counter-Strike 2"
    assert summary["top_percent"] == 80


def test_summarize_survives_an_empty_library():
    summary = stats.summarize([])
    assert summary["game_count"] == 0
    assert summary["played_percent"] == 0
    assert summary["top_game"] is None
    assert summary["top_percent"] == 0


def test_top_games_skip_the_unplayed():
    assert names(stats.top_games(LIBRARY, 2)) == ["Counter-Strike 2", "Elden Ring"]
    assert len(stats.top_games(LIBRARY, 10)) == 3


def test_recent_games_are_ordered_by_the_last_two_weeks():
    assert names(stats.recent_games(LIBRARY, 5)) == ["celeste", "Counter-Strike 2"]


def test_find_game_gives_the_rank():
    game, rank = stats.find_game(LIBRARY, 2)
    assert (game["name"], rank) == ("Elden Ring", 2)
    assert stats.find_game(LIBRARY, 999) is None


def test_sort_orders():
    assert names(stats.sort_games(LIBRARY, "hours"))[:3] == ["Counter-Strike 2", "Elden Ring", "celeste"]
    assert names(stats.sort_games(LIBRARY, "recent")) == ["celeste", "Counter-Strike 2", "Elden Ring"]
    assert names(stats.sort_games(LIBRARY, "never")) == ["Among Us", "Hades II"]
    assert names(stats.sort_games(LIBRARY, "name")) == ["Among Us", "celeste", "Counter-Strike 2", "Elden Ring", "Hades II"]


def test_unknown_sort_order_falls_back_to_most_played():
    assert stats.sort_games(LIBRARY, "nonsense") == stats.sort_games(LIBRARY, "hours")


def test_every_sort_choice_has_a_label():
    assert stats.sort_choices()[0] == ("hours", "Most played")
    assert len(stats.sort_choices()) == len(stats.SORT_ORDERS)


def test_search_ignores_case_and_spaces():
    assert names(stats.search_games(LIBRARY, "  ELDEN ")) == ["Elden Ring"]
    assert stats.search_games(LIBRARY, "") == LIBRARY
    assert stats.search_games(LIBRARY, "zzz") == []


def test_playtime_bands():
    edges = [1, 10, 50, 100]
    assert stats.band_labels(edges) == ["never", "under 1 h", "1–10 h", "10–50 h", "50–100 h", "100 h +"]
    games = [
        make_game(1, "never"),
        make_game(2, "half an hour", hours=0.5),
        make_game(3, "exactly one hour", hours=1),
        make_game(4, "nine hours", hours=9),
        make_game(5, "fifty hours", hours=50),
        make_game(6, "a thousand hours", hours=1000),
    ]
    assert stats.count_by_band(games, edges) == [1, 1, 2, 0, 1, 1]


# --- trophies.exe ---

TROPHY_GAMES = [
    {"app_id": 1, "name": "Hades", "icon": None, "unlocked": 49, "total": 49, "last_unlock": 3000},
    {"app_id": 2, "name": "celeste", "icon": None, "unlocked": 30, "total": 32, "last_unlock": 5000},
    {"app_id": 3, "name": "Portal 2", "icon": None, "unlocked": 10, "total": 51, "last_unlock": None},
    {"app_id": 4, "name": "Among Us", "icon": None, "unlocked": 0, "total": 20, "last_unlock": None},
]


def trophy_order(order):
    return [game["name"] for game in stats.sort_trophies(TROPHY_GAMES, order)]


def test_trophy_orders():
    assert trophy_order("latest") == ["celeste", "Hades", "Among Us", "Portal 2"]  # undated ones last, A to Z
    assert trophy_order("closest") == ["celeste", "Portal 2", "Among Us"]  # finished games aren't "close"
    assert trophy_order("most") == ["Hades", "celeste", "Portal 2", "Among Us"]
    assert trophy_order("perfect") == ["Hades"]
    assert trophy_order("untouched") == ["Among Us"]
    assert trophy_order("name") == ["Among Us", "celeste", "Hades", "Portal 2"]
    assert trophy_order("no such order") == trophy_order("latest")
    assert [key for key, _ in stats.trophy_choices()] == list(stats.TROPHY_ORDERS)


def test_achievement_overview_averages_only_started_games():
    overview = stats.achievement_overview(TROPHY_GAMES)
    assert overview == {"unlocked": 89, "total": 152, "games": 4, "started": 3, "perfect": 1, "average": 71}  # (100% + 94% + 20%) / 3
    assert stats.achievement_overview([])["average"] == 0
    assert stats.completion(TROPHY_GAMES[1]) == 94
