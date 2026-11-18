"""A scan: ask Steam about one player and save what comes back."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import api
import config
import storage

# What the sync window says while each step runs.
STEPS = (
    "Finding the profile",
    "Reading the profile card",
    "Downloading the library",
    "Saving today's snapshot",
    "Checking achievements",
)

# Problems with one game's achievements that shouldn't stop the scan. The
# game simply isn't marked as checked, so the next scan tries it again.
SKIPPABLE = (api.SteamTimeout, api.NoConnection, api.SteamDown)


def is_fresh(player: dict | None) -> bool:
    """True if this player was scanned recently enough that we can leave Steam alone."""
    return bool(player) and time.time() - player["synced_at"] < config.CACHE_MINUTES * 60


def scan(query: str, force: bool = False):
    """Scan one player, reporting progress along the way.

    This is a generator. Instead of returning once at the end, it hands back
    a small dict before each step ({"label": "Downloading the library"}), so
    the page can move its progress bar while the work is still going on.
    During a long step it may also send {"detail": "12/40"}. The last dict
    it yields is the result: {"steam_id": ..., "gained": minutes}.

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

    yield {"label": STEPS[4]}
    for done, todo in check_achievements(steam_id, games):
        yield {"detail": f"{done}/{todo}"}
    yield {"steam_id": steam_id, "gained": gained}


def games_to_check(games: list[dict], checked_minutes: dict[int, int]) -> list[dict]:
    """The games whose achievements might have changed since they were last checked.

    Only played games that have achievements at all, and of those only the
    ones played since the last check. Achievements only unlock while playing,
    so on a normal day this is a handful of games, not the whole library.
    """
    return [
        game
        for game in games
        if game.get("has_stats") and game["minutes"] > checked_minutes.get(game["app_id"], 0)
    ]


def check_achievements(steam_id: str, games: list[dict]):
    """Ask Steam about the games from games_to_check, a few at a time.

    Yields (done, todo) after each game. Achievements are extra, so trouble
    here never fails the scan: a game that couldn't be checked is tried again
    next time, and if Steam asks to slow down or the achievements are
    private, the rest wait for the next scan.
    """
    todo = games_to_check(games, storage.get_checked_minutes(steam_id))
    if not todo:
        return
    pool = ThreadPoolExecutor(max_workers=config.ACHIEVEMENT_WORKERS)
    try:
        asked = {pool.submit(api.get_achievements, steam_id, game["app_id"]): game for game in todo}
        for done, answer in enumerate(as_completed(asked), start=1):
            game = asked[answer]
            try:
                # Saved here, on this thread, so only one thread ever writes to the database.
                storage.save_achievements(steam_id, game["app_id"], game["minutes"], answer.result())
            except SKIPPABLE:
                pass
            except (api.RateLimited, api.PrivateAchievements):
                return
            yield done, len(todo)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)  # don't start games that haven't been asked about yet
