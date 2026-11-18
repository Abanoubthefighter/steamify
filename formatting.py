"""Small helpers that turn raw numbers into words for the screen.

app.py registers these as Jinja filters, so a template can write
{{ game.minutes | hours }} and never has to do maths itself.
"""

import re
import time
from datetime import datetime

MINUTE, HOUR, DAY = 60, 3600, 86400

# (use this row while the gap is under `limit` seconds, seconds per unit, unit name)
_AGO_STEPS = [
    (HOUR, MINUTE, "minute"),
    (DAY, HOUR, "hour"),
    (14 * DAY, DAY, "day"),
    (60 * DAY, 7 * DAY, "week"),
    (365 * DAY, 30 * DAY, "month"),
]


def hours(minutes: int) -> str:
    """Playtime the way a person would say it: 45 min, 6.2 h, 812 h, 2,481 h."""
    if minutes < 60:
        return f"{minutes} min"
    value = minutes / 60
    if round(value, 1) < 10:
        return f"{value:.1f} h"
    return f"{round(value):,} h"


def number(count: int) -> str:
    """A whole number with thousands commas: 1284 becomes 1,284."""
    return f"{count:,}"


def share(percent: float) -> str:
    """A share of players: 0.8%, 4%, 61%. Below 10 one decimal is worth showing."""
    if percent < 0.1:
        return "under 0.1%"
    if percent < 10:
        return f"{percent:.1f}%".replace(".0%", "%")
    return f"{round(percent)}%"


def plural(count: int, word: str) -> str:
    """1 game, 42 games. Only for words that take a plain "s"."""
    return f"{count:,} {word}" if count == 1 else f"{count:,} {word}s"


def time_ago(timestamp: int | None, now: float | None = None) -> str:
    """A unix time as "4 minutes ago", "yesterday", "3 weeks ago" or "never"."""
    if not timestamp:
        return "never"
    seconds = max(0, (now or time.time()) - timestamp)
    if seconds < MINUTE:
        return "just now"
    for limit, size, word in _AGO_STEPS:
        if seconds < limit:
            count = int(seconds // size)
            if (count, word) == (1, "day"):
                return "yesterday"
            return f"{plural(count, word)} ago"
    return f"{plural(int(seconds // (365 * DAY)), 'year')} ago"


def last_played(game: dict, now: float | None = None) -> str:
    """When a game was last opened, in words. Steam has no date for some very old sessions."""
    if game["last_played"]:
        return time_ago(game["last_played"], now)
    return "a long time ago" if game["minutes"] else "never"


def long_date(timestamp: int | None) -> str:
    """A unix time as "12 Mar 2024"."""
    if not timestamp:
        return "unknown"
    moment = datetime.fromtimestamp(timestamp)
    return f"{moment.day} {moment:%b %Y}"


def year(timestamp: int) -> str:
    """Just the year of a unix time, for "Member since 2017"."""
    return str(datetime.fromtimestamp(timestamp).year)


def filename(name: str) -> str:
    """Counter-Strike 2 -> counter_strike_2, for the pretend file names in title bars."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "game"
