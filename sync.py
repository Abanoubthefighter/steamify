"""A scan: ask Steam about one player and save what comes back."""

import time

import api
import config
import storage

# What the sync window says while each step runs.
STEPS = (
    "Finding the profile",
    "Reading the profile card",
    "Downloading the library",
    "Saving today's snapshot",
)


def is_fresh(player: dict | None) -> bool:
    """True if this player was scanned recently enough that we can leave Steam alone."""
    return bool(player) and time.time() - player["synced_at"] < config.CACHE_MINUTES * 60


def scan(query: str, force: bool = False):
    """Scan one player, reporting progress along the way.

    This is a generator. Instead of returning once at the end, it hands back
    a small dict before each step ({"label": "Downloading the library"}), so
    the page can move its progress bar while the work is still going on. The
    last dict it yields is the result: {"steam_id": ..., "gained": minutes}.

    `query` is whatever the user typed. `force` skips the "scanned recently"
    shortcut. Raises api.SteamError if Steam can't or won't answer.
    """
    yield {"label": STEPS[0]}
    steam_id = api.resolve_steam_id(query)
    if not force and is_fresh(storage.get_player(steam_id)):
        yield {"steam_id": steam_id, "gained": 0}
        return

    yield {"label": STEPS[1]}
    profile = api.get_player(steam_id)
    profile["level"] = api.get_level(steam_id)

    yield {"label": STEPS[2]}
    games = api.get_owned_games(steam_id)

    yield {"label": STEPS[3]}
    gained = storage.save_snapshot(profile, games)
    yield {"steam_id": steam_id, "gained": gained}
