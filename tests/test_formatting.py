"""Formatting tests: numbers in, words out."""

import pytest

import formatting

NOW = 1_762_776_000
MINUTE, HOUR, DAY = 60, 3600, 86400


@pytest.mark.parametrize(
    "minutes, text",
    [
        (0, "0 min"),
        (45, "45 min"),
        (60, "1.0 h"),
        (372, "6.2 h"),
        (599, "10 h"),  # 9.98 h rounds up, so it shouldn't print as "10.0 h"
        (5760, "96 h"),
        (148860, "2,481 h"),
    ],
)
def test_hours(minutes, text):
    assert formatting.hours(minutes) == text


@pytest.mark.parametrize(
    "seconds_back, text",
    [
        (5, "just now"),
        (4 * MINUTE, "4 minutes ago"),
        (HOUR, "1 hour ago"),
        (30 * HOUR, "yesterday"),
        (5 * DAY, "5 days ago"),
        (21 * DAY, "3 weeks ago"),
        (100 * DAY, "3 months ago"),
        (800 * DAY, "2 years ago"),
    ],
)
def test_time_ago(seconds_back, text):
    assert formatting.time_ago(NOW - seconds_back, now=NOW) == text


def test_time_ago_without_a_time():
    assert formatting.time_ago(None) == "never"
    assert formatting.time_ago(0) == "never"


def test_plural():
    assert formatting.plural(1, "game") == "1 game"
    assert formatting.plural(0, "game") == "0 games"
    assert formatting.plural(1500, "game") == "1,500 games"


def test_filename():
    assert formatting.filename("Counter-Strike 2") == "counter_strike_2"
    assert formatting.filename("Baldur's Gate 3") == "baldur_s_gate_3"
    assert formatting.filename("???") == "game"


def test_dates():
    assert formatting.year(1489500000) == "2017"
    assert formatting.long_date(None) == "unknown"
    assert formatting.long_date(1489500000).endswith("Mar 2017")


def test_number_gets_thousands_commas():
    assert formatting.number(1284) == "1,284"
    assert formatting.number(7) == "7"


@pytest.mark.parametrize(("percent", "text"), [(61.4, "61%"), (12.5, "12%"), (4.0, "4%"), (0.8, "0.8%"), (0.04, "under 0.1%")])
def test_share_of_players(percent, text):
    assert formatting.share(percent) == text


def test_every():
    assert formatting.every(60) == "hour"
    assert formatting.every(120) == "2 hours"
    assert formatting.every(30) == "30 minutes"
