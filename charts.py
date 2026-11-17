"""Shapes the numbers for the three charts in the media player window.

This file decides *what* each chart shows: the labels, the values and which
bars get highlighted. static/js/charts.js only draws what it's handed, so
changing a chart (or adding one) mostly means editing Python.

Each chart is a "track", because the window is a media player. A track has
one or more "views" that the buttons under the screen switch between, for
example 30D / 6M / 1Y / ALL on the history track.
"""

from datetime import date, timedelta

import config
import stats
import storage
from formatting import hours, long_date, plural

NAME_LIMIT = 24  # longest game name that fits beside a bar before it gets cut


def build_tracks(player: dict, games: list[dict], summary: dict, today: date | None = None) -> list[dict]:
    """Everything the media player needs, as plain data that can be sent to the page as JSON."""
    today = today or date.today()
    return [
        history_track(player, summary, today),
        top_games_track(games, summary),
        backlog_track(games, summary),
    ]


def _view(key, labels, values, titles=None, notes=None, colors=None, marked=None) -> dict:
    """One view of a track. Views are kept in a list, so their buttons appear in the order they were built.

    key:    the text on the view's button
    labels: short text under each bar          titles: the long version, for tooltips
    values: bar heights                        notes:  an extra line for each tooltip
    colors: theme colour name for each bar     marked: which bars get their value printed on them
    """
    count = len(values)
    return {
        "key": key,
        "labels": labels,
        "titles": titles or labels,
        "values": values,
        "notes": notes or [""] * count,
        "colors": colors or ["lilac"] * count,
        "marked": list(range(count)) if marked is None else marked,
    }


# --- Track 1: hours played over time -----------------------------------------


def history_track(player: dict, summary: dict, today: date) -> dict:
    steam_id = player["steam_id"]
    first_day = storage.first_log_day(steam_id)

    views = []
    for key, (size, count) in config.HISTORY_RANGES.items():
        buckets = _buckets(size, count, today, first_day)
        # ISO dates sort like plain text, so "2026-06" works as a start date
        # for months just as "2026-06-17" does for days.
        rows = storage.get_history(steam_id, since=buckets[0], bucket=size)
        views.append(_history_view(key, buckets, rows, size))

    return {
        "file": "playtime_history.wmv",
        "title": "Hours played over time",
        "caption": f"{hours(summary['total_minutes'])} total",
        "footnote": f"logging since {long_date(player['first_seen'])}",
        "unit": "h",
        "horizontal": False,
        "start": config.DEFAULT_HISTORY_RANGE,
        "legend": [["red", "still going"], ["sand", "best"]],
        "empty": (
            "No history yet. Steam doesn't keep one, so I build it from the "
            "difference between scans. Play something and come back."
        ),
        "views": views,
    }


def _buckets(size: str, count: int | None, today: date, first_day: str | None) -> list[str]:
    """Every period a view should show, oldest first, empty ones included.

    Days look like "2026-11-17" and months like "2026-11", the same text
    storage.get_history uses for its buckets.
    """
    if size == "day":
        if count is None:
            count = (today - date.fromisoformat(first_day)).days + 1 if first_day else 1
        return [(today - timedelta(days=back)).isoformat() for back in range(count - 1, -1, -1)]

    if count is None:
        start = date.fromisoformat(first_day) if first_day else today
        count = (today.year - start.year) * 12 + today.month - start.month + 1
    return last_months(count, today)


def last_months(count: int, today: date) -> list[str]:
    """The last `count` months up to and including this one: ["2026-09", "2026-10", "2026-11"]."""
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(f"{year}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return months[::-1]


def _history_view(key: str, buckets: list[str], rows: list[dict], size: str) -> dict:
    """Line the logged rows up against the full list of periods and pick the bars to highlight."""
    logged = {row["bucket"]: row for row in rows}
    values = [round(logged[bucket]["minutes"] / 60, 1) if bucket in logged else 0 for bucket in buckets]
    notes = [f"mostly {logged[bucket]['top_game']}" if bucket in logged else "nothing logged" for bucket in buckets]

    last = len(buckets) - 1
    colors = ["lilac"] * len(buckets)
    marked = []
    if any(values):
        best = values.index(max(values))
        colors[best] = "sand"
        marked.append(best)
    colors[last] = "red"  # the period we're still in, so its bar can still grow
    if values[last] and last not in marked:
        marked.append(last)

    labels, titles = zip(*(_period_names(bucket, size, many=len(buckets) > 12) for bucket in buckets))
    return _view(key, list(labels), values, list(titles), notes, colors, marked)


def _period_names(bucket: str, size: str, many: bool) -> tuple[str, str]:
    """(short label for the axis, long title for the tooltip) for one day or month."""
    if size == "day":
        day = date.fromisoformat(bucket)
        return f"{day.day} {day:%b}", f"{day:%A} {day.day} {day:%B}"
    month = date.fromisoformat(bucket + "-01")
    short = f"{month:%b}".upper()
    if many or month.month == 1:  # long ranges repeat month names, so show which year
        short += f" {month:%y}"
    return short, f"{month:%B %Y}"


# --- Track 2: most played games ----------------------------------------------


def top_games_track(games: list[dict], summary: dict) -> dict:
    all_time = stats.top_games(games, config.CHART_GAMES_COUNT)
    two_weeks = stats.recent_games(games, config.CHART_GAMES_COUNT)
    return {
        "file": "top_games.wmv",
        "title": "Most played games",
        "caption": f"top {len(all_time)} of {plural(summary['game_count'], 'game')}",
        "footnote": "",
        "unit": "h",
        "horizontal": True,
        "start": "ALL TIME",
        "legend": [],
        "empty": "Nothing played in this stretch, so there's no top anything.",
        "views": [
            _ranking_view("ALL TIME", all_time, "minutes", summary["total_minutes"], "of all your playtime"),
            _ranking_view("2 WEEKS", two_weeks, "minutes_2weeks", summary["recent_minutes"], "of the last two weeks"),
        ],
    }


def _ranking_view(key: str, games: list[dict], field: str, total: int, of_what: str) -> dict:
    names = [game["name"] for game in games]
    return _view(
        key,
        labels=[_shorten(name) for name in names],
        values=[round(game[field] / 60, 1) for game in games],
        titles=names,
        notes=[f"{stats.percent(game[field], total)}% {of_what}" for game in games],
    )


def _shorten(name: str) -> str:
    return name if len(name) <= NAME_LIMIT else name[: NAME_LIMIT - 1].rstrip() + "…"


# --- Track 3: how far each game got ------------------------------------------


def backlog_track(games: list[dict], summary: dict) -> dict:
    counts = stats.count_by_band(games, config.PLAYTIME_EDGES)
    return {
        "file": "backlog.wmv",
        "title": "How far you got into your games",
        "caption": f"{summary['played_count']} of {summary['game_count']} played",
        "footnote": "",
        "unit": "games",
        "horizontal": False,
        "start": "ALL",
        "legend": [["red", "never launched"]],
        "empty": "This library is empty, so there's nothing to sort into piles.",
        "views": [
            _view(
                "ALL",
                labels=stats.band_labels(config.PLAYTIME_EDGES),
                values=counts,
                notes=[f"{stats.percent(count, summary['game_count'])}% of your library" for count in counts],
                colors=["red"] + ["lilac"] * (len(counts) - 1),
            )
        ],
    }
