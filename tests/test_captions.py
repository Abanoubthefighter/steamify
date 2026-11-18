"""The popups in warning.exe: does the right one show up for the right numbers?"""

import pytest

import captions
import config
import stats
from conftest import make_game

NOW = 1_762_776_000
DAY = 86400


def alerts_for(games, **kwargs):
    return captions.build_alerts(games, stats.summarize(games), now=NOW, **kwargs)


def texts(alerts):
    return [alert["text"] for alert in alerts]


def test_empty_library_has_nothing_to_say():
    assert alerts_for([]) == []


def test_backlog_counts_the_unplayed():
    games = [make_game(1, "Played", hours=5, recent_hours=1), make_game(2, "Unplayed"), make_game(3, "Also unplayed")]
    backlog = alerts_for(games)[0]
    assert backlog["big"] == "2"
    assert backlog["text"] == "games never launched"
    assert "half" in backlog["caption"]


def test_backlog_uses_the_singular_for_one_game():
    games = [make_game(number, f"Game {number}", hours=3, recent_hours=1) for number in range(9)] + [make_game(99, "Unplayed")]
    backlog = alerts_for(games)[0]
    assert (backlog["big"], backlog["text"]) == ("1", "game never launched")
    assert "Just the one" in backlog["caption"]


def test_a_fully_played_library_gets_congratulated():
    assert alerts_for([make_game(1, "Played", hours=5, recent_hours=1)])[0]["big"] == "0"


def test_obsession_needs_a_big_enough_share():
    lopsided = [make_game(1, "Dota 2", hours=900, recent_hours=1), make_game(2, "Portal", hours=100)]
    balanced = [make_game(number, f"Game {number}", hours=10, recent_hours=1) for number in range(10)]
    assert "of your playtime is Dota 2" in texts(alerts_for(lopsided))
    assert not any("of your playtime" in text for text in texts(alerts_for(balanced)))


def test_abandoned_favourite():
    long_ago = NOW - (config.ABANDONED_DAYS + 30) * DAY
    games = [make_game(1, "Skyrim", hours=300, last_played=long_ago), make_game(2, "Hades", hours=20, recent_hours=2, last_played=NOW)]
    alert = captions.abandoned_alert(games, now=NOW)
    assert alert["big"] == "300 h"
    assert alert["text"].startswith("in Skyrim, untouched since")
    assert captions.abandoned_alert([games[1]], now=NOW) is None


def test_quiet_fortnight_and_binge():
    quiet = captions.fortnight_alert(stats.summarize([make_game(1, "Hades", hours=20)]))
    binge = captions.fortnight_alert(stats.summarize([make_game(1, "Hades", hours=200, recent_hours=config.BINGE_HOURS + 5)]))
    normal = captions.fortnight_alert(stats.summarize([make_game(1, "Hades", hours=200, recent_hours=3)]))
    assert (quiet["big"], quiet["text"]) == ("0 h", "played in the last two weeks")
    assert binge["big"] == f"{config.BINGE_HOURS + 5} h"
    assert normal is None  # an ordinary fortnight isn't worth a popup


def test_lifetime_is_counted_in_days():
    alert = captions.lifetime_alert(stats.summarize([make_game(1, "Hades", hours=48)]))
    assert (alert["big"], alert["text"]) == ("2", "full days spent on Steam")
    assert captions.lifetime_alert(stats.summarize([make_game(1, "Hades", hours=3)])) is None


def test_demo_notice_comes_first_and_the_list_is_capped():
    games = [make_game(1, "Dota 2", hours=5000, recent_hours=80, last_played=NOW)] + [make_game(2, "Unplayed")]
    alerts = alerts_for(games, is_demo=True)
    assert alerts[0] is captions.DEMO_ALERT
    assert len(alerts) <= config.MAX_ALERTS


def test_versus_caption_knows_who_is_ahead():
    assert "You're 2.0 h ahead" in captions.versus_caption("sam", 120)
    assert captions.versus_caption("sam", -120).startswith("sam is 2.0 h ahead")
    assert "tie" in captions.versus_caption("sam", 0)


@pytest.mark.parametrize(
    ("perfect", "percent", "words"),
    [(12, 40, "Completionist"), (0, 70, "More than half"), (2, 30, "done to 100%"), (0, 5, "collect games"), (0, 30, "Plenty")],
)
def test_achievement_caption_picks_a_line_for_the_numbers(perfect, percent, words):
    assert words in captions.achievement_caption({"perfect": perfect}, percent)
