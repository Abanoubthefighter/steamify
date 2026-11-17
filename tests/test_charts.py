"""Chart data: the right bars, in the right order, with the right ones highlighted."""

import json
from datetime import date

import charts
import config
import stats
import storage
from conftest import make_game, make_profile

ME = "76561198000000001"
TODAY = date(2026, 11, 17)
FIRST_SCAN = 1_780_000_000  # late May 2026


def build(games, history=()):
    storage.save_snapshot(make_profile(ME), games, now=FIRST_SCAN)
    storage.add_history(ME, list(history))
    player = storage.get_player(ME)
    return charts.build_tracks(player, games, stats.summarize(games), today=TODAY)


def view(track, key):
    return next(each for each in track["views"] if each["key"] == key)


def test_last_months_crosses_new_year():
    assert charts.last_months(3, date(2026, 1, 15)) == ["2025-11", "2025-12", "2026-01"]
    assert charts.last_months(1, TODAY) == ["2026-11"]


def test_three_tracks_that_survive_a_trip_through_json():
    tracks = json.loads(json.dumps(build([make_game(1, "Hades", hours=20)]), sort_keys=True))
    assert [track["file"] for track in tracks] == ["playtime_history.wmv", "top_games.wmv", "backlog.wmv"]
    for track in tracks:
        assert track["start"] in [each["key"] for each in track["views"]]
        for each in track["views"]:
            sizes = {len(each[field]) for field in ("labels", "titles", "values", "notes", "colors")}
            assert len(sizes) == 1, "every bar needs a label, a title, a value, a note and a colour"


def test_history_views_follow_the_configured_ranges_in_order():
    history = build([make_game(1, "Hades", hours=20)])[0]
    assert [each["key"] for each in history["views"]] == list(config.HISTORY_RANGES)
    assert len(view(history, "30D")["values"]) == 30
    assert view(history, "6M")["labels"] == ["JUN", "JUL", "AUG", "SEP", "OCT", "NOV"]
    assert view(history, "1Y")["labels"][1] == "JAN 26"  # January shows the year


def test_history_fills_gaps_and_highlights_best_and_current():
    rows = [("2026-08-10", 1, 600), ("2026-08-11", 2, 60), ("2026-11-03", 1, 120)]
    history = build([make_game(1, "Hades", hours=20), make_game(2, "Celeste", hours=5)], rows)[0]
    six_months = view(history, "6M")
    assert six_months["values"] == [0, 0, 11.0, 0, 0, 2.0]
    assert six_months["colors"] == ["lilac", "lilac", "cream", "lilac", "lilac", "red"]
    assert six_months["marked"] == [2, 5]
    assert six_months["notes"][2] == "mostly Hades, the best in view"
    assert six_months["notes"][5] == "mostly Hades, still going"
    assert six_months["notes"][0] == "nothing logged"
    assert six_months["titles"][5] == "November 2026"


def test_all_time_view_starts_at_the_first_logged_month():
    history = build([make_game(1, "Hades", hours=20)], [("2026-09-30", 1, 30)])[0]
    assert view(history, "ALL")["titles"] == ["September 2026", "October 2026", "November 2026"]


def test_history_with_nothing_logged_is_all_zeros():
    history = build([make_game(1, "Hades", hours=20)])[0]
    assert not any(view(history, "ALL")["values"])
    assert view(history, "ALL")["marked"] == []
    assert history["empty"]


def test_top_games_track_has_both_views():
    games = [
        make_game(1, "Counter-Strike 2", hours=800, recent_hours=1),
        make_game(2, "A Game With A Really Long Name That Goes On", hours=200, recent_hours=3),
        make_game(3, "Unplayed"),
    ]
    top = build(games)[1]
    all_time, two_weeks = view(top, "ALL TIME"), view(top, "2 WEEKS")
    assert all_time["values"] == [800.0, 200.0]
    assert all_time["notes"][0] == "80% of all your playtime"
    assert all_time["labels"][1].endswith("…") and len(all_time["labels"][1]) <= charts.NAME_LIMIT
    assert all_time["titles"][1] == "A Game With A Really Long Name That Goes On"
    assert two_weeks["titles"] == ["A Game With A Really Long Name That Goes On", "Counter-Strike 2"]
    assert top["horizontal"] is True


def test_backlog_track_counts_games_per_band():
    games = [make_game(1, "Never"), make_game(2, "Never either"), make_game(3, "Dabbled", hours=0.5), make_game(4, "Loved", hours=500)]
    backlog = build(games)[2]
    bands = view(backlog, "ALL")
    assert bands["values"] == [2, 1, 0, 0, 0, 1]
    assert bands["colors"][0] == "red"
    assert bands["notes"][0] == "50% of your library"
    assert backlog["caption"] == "2 of 4 played"
