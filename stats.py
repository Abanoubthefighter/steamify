"""Number crunching over a list of games.

Every function here takes plain data in and gives plain data back. No
database, no network, no Flask. That also makes this the easiest file in
the project to test.

A "game" is a dict shaped like this (storage.get_library returns a list of them):

    {"app_id": 730, "name": "Counter-Strike 2", "icon": "8dbc7195...",
     "minutes": 48720, "minutes_2weeks": 372, "last_played": 1731800000}
"""

from bisect import bisect_right


def percent(part: float, whole: float) -> int:
    """A whole-number percentage that doesn't blow up on an empty library."""
    return round(100 * part / whole) if whole else 0


def summarize(games: list[dict]) -> dict:
    """The headline numbers for a library."""
    played = [game for game in games if game["minutes"] > 0]
    total = sum(game["minutes"] for game in played)
    top = max(played, key=lambda game: game["minutes"], default=None)
    recent = [game for game in games if game["minutes_2weeks"] > 0]
    return {
        "game_count": len(games),
        "played_count": len(played),
        "never_count": len(games) - len(played),
        "played_percent": percent(len(played), len(games)),
        "total_minutes": total,
        "recent_minutes": sum(game["minutes_2weeks"] for game in recent),
        "recent_count": len(recent),
        "top_game": top,
        "top_percent": percent(top["minutes"], total) if top else 0,
    }


# --- Picking games -----------------------------------------------------------


def top_games(games: list[dict], count: int) -> list[dict]:
    """The most played games, biggest first. Never-played games don't count."""
    return _most_played(game for game in games if game["minutes"] > 0)[:count]


def recent_games(games: list[dict], count: int) -> list[dict]:
    """Games played in the last two weeks, most played first."""
    active = [game for game in games if game["minutes_2weeks"] > 0]
    return sorted(active, key=lambda game: (-game["minutes_2weeks"], _name_key(game)))[:count]


def find_game(games: list[dict], app_id: int) -> tuple[dict, int] | None:
    """One game and its rank by playtime (1 = most played), or None if it isn't owned."""
    for rank, game in enumerate(_most_played(games), start=1):
        if game["app_id"] == app_id:
            return game, rank
    return None


# --- Sorting and searching (sort.exe and library.exe) ------------------------


def _name_key(game: dict) -> str:
    return game["name"].casefold()


def _most_played(games) -> list[dict]:
    return sorted(games, key=lambda game: (-game["minutes"], _name_key(game)))


def _recently_played(games) -> list[dict]:
    touched = [game for game in games if game["last_played"]]
    return sorted(touched, key=lambda game: (-game["last_played"], _name_key(game)))


def _never_played(games) -> list[dict]:
    return sorted((game for game in games if game["minutes"] == 0), key=_name_key)


def _a_to_z(games) -> list[dict]:
    return sorted(games, key=_name_key)


# The choices in sort.exe: key -> (label on the radio button, function that orders the list).
# To add one, write a function like the four above and list it here.
SORT_ORDERS = {
    "hours": ("Most played", _most_played),
    "recent": ("Recently played", _recently_played),
    "never": ("Never played", _never_played),
    "name": ("A to Z", _a_to_z),
}
DEFAULT_SORT = "hours"


def sort_choices() -> list[tuple[str, str]]:
    """(key, label) pairs for the radio buttons."""
    return [(key, label) for key, (label, _) in SORT_ORDERS.items()]


def sort_games(games: list[dict], order: str = DEFAULT_SORT) -> list[dict]:
    """Order (and for "never", filter) the library. Unknown orders fall back to the default."""
    _, sorter = SORT_ORDERS.get(order, SORT_ORDERS[DEFAULT_SORT])
    return sorter(games)


def search_games(games: list[dict], text: str) -> list[dict]:
    """Games whose name contains the text, ignoring case. Empty text matches everything."""
    needle = text.casefold().strip()
    if not needle:
        return list(games)
    return [game for game in games if needle in _name_key(game)]


# --- Achievements per game (trophies.exe) ------------------------------------
# These take the games from storage.get_achievement_games:
# {"app_id", "name", "icon", "unlocked", "total", "last_unlock"}


def completion(game: dict) -> int:
    """How much of a game's achievements are unlocked, in whole percent."""
    return percent(game["unlocked"], game["total"])


def _latest_unlock(games) -> list[dict]:
    # Games with no dated unlock count as 0, so they end up at the bottom.
    return sorted(games, key=lambda game: (-(game["last_unlock"] or 0), _name_key(game)))


def _closest_to_perfect(games) -> list[dict]:
    unfinished = [game for game in games if game["unlocked"] < game["total"]]
    return sorted(unfinished, key=lambda game: (-game["unlocked"] / game["total"], game["total"] - game["unlocked"], _name_key(game)))


def _most_unlocked(games) -> list[dict]:
    return sorted(games, key=lambda game: (-game["unlocked"], _name_key(game)))


def _perfect_only(games) -> list[dict]:
    return _latest_unlock(game for game in games if game["unlocked"] == game["total"])


def _not_started(games) -> list[dict]:
    return sorted((game for game in games if game["unlocked"] == 0), key=_name_key)


# The choices in trophies.exe, built the same way as SORT_ORDERS above.
TROPHY_ORDERS = {
    "latest": ("Latest unlock", _latest_unlock),
    "closest": ("Closest to perfect", _closest_to_perfect),
    "most": ("Most unlocked", _most_unlocked),
    "perfect": ("Perfect only", _perfect_only),
    "untouched": ("Not started", _not_started),
    "name": ("A to Z", _a_to_z),
}
DEFAULT_TROPHY_ORDER = "latest"


def trophy_choices() -> list[tuple[str, str]]:
    """(key, label) pairs for the radio buttons in trophies.exe."""
    return [(key, label) for key, (label, _) in TROPHY_ORDERS.items()]


def sort_trophies(games: list[dict], order: str = DEFAULT_TROPHY_ORDER) -> list[dict]:
    """Order (and for some orders, filter) the games. Unknown orders fall back to the default."""
    _, sorter = TROPHY_ORDERS.get(order, TROPHY_ORDERS[DEFAULT_TROPHY_ORDER])
    return sorter(games)


def achievement_overview(games: list[dict]) -> dict:
    """The headline numbers at the top of trophies.exe.

    "average" is the average completion of the games you've unlocked at
    least one achievement in, the way Steam's own profile counts it. A game
    you never started doesn't drag it down.
    """
    started = [game for game in games if game["unlocked"]]
    average = sum(game["unlocked"] / game["total"] for game in started) / len(started) if started else 0
    return {
        "unlocked": sum(game["unlocked"] for game in games),
        "total": sum(game["total"] for game in games),
        "games": len(games),
        "started": len(started),
        "perfect": sum(1 for game in games if game["unlocked"] == game["total"]),
        "average": round(100 * average),
    }


# --- Grouping by playtime (the backlog chart) --------------------------------


def band_labels(edges: list[int]) -> list[str]:
    """Names for the playtime bands: [1, 10] -> never, under 1 h, 1-10 h, 10 h +."""
    middle = [f"{low}–{high} h" for low, high in zip(edges, edges[1:])]
    return ["never", f"under {edges[0]} h", *middle, f"{edges[-1]} h +"]


def count_by_band(games: list[dict], edges: list[int]) -> list[int]:
    """How many games fall in each band. `edges` are in hours, smallest first."""
    edges_in_minutes = [hours * 60 for hours in edges]
    counts = [0] * (len(edges) + 2)
    for game in games:
        # Band 0 is "never". bisect finds which gap between edges the playtime falls in.
        band = 0 if game["minutes"] == 0 else 1 + bisect_right(edges_in_minutes, game["minutes"])
        counts[band] += 1
    return counts
