"""A scan: ask Steam about one player and save what comes back."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import api
import config
import storage
from formatting import DAY

# What the sync window says while each step runs.
STEPS = (
    "Finding the profile",
    "Reading the profile card",
    "Downloading the library",
    "Saving today's snapshot",
    "Checking achievements",
    "Checking how rare they are",
)

# Problems with one game that shouldn't stop the scan. That game simply
# isn't marked as checked, so the next scan tries it again.
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
    for detail in check_achievements(steam_id, games):
        yield {"detail": detail}

    yield {"label": STEPS[5]}
    for done, todo in check_rarity(steam_id):
        yield {"detail": f"{done}/{todo}"}
    fetch_missing_icons(steam_id)

    yield {"steam_id": steam_id, "gained": gained}


# --- Achievements ------------------------------------------------------------
# Steam has one call per game, so these steps choose carefully what to ask,
# ask a few games at a time, and never fail the scan: achievements are extra.


def games_to_check(games: list[dict], checked_minutes: dict[int, int]) -> list[dict]:
    """The games whose achievements might have changed since they were last checked.

    That's every game played since its last check (all played games, the
    first time). Achievements only unlock while playing, so on a normal day
    this is a handful of games, not the whole library.

    Steam flags the games that have achievements ("has_stats"), but the flag
    isn't always right, so unflagged games are asked about too, after the
    flagged ones. One that turns out to have none is saved as such, and only
    asked about again once it's been played more.
    """
    todo = [game for game in games if game["minutes"] > checked_minutes.get(game["app_id"], 0)]
    return sorted(todo, key=lambda game: not game.get("has_stats"))  # flagged first; otherwise same order


def check_achievements(steam_id: str, games: list[dict]):
    """Ask Steam about the games from games_to_check.

    Yields a progress line for the sync window after each game ("12/40").
    If Steam says "slow down", this waits a bit and carries on one game at a
    time, a few times over (config.SLOW_DOWN_RETRIES), before leaving the
    rest for the next scan. Before, it gave up at the first "slow down",
    and a big library could stay half-checked for a long time.
    """
    todo = games_to_check(games, storage.get_checked_minutes(steam_id))
    waiting = list(todo)
    done = 0

    def ask(game: dict) -> list[dict]:
        return api.get_achievements(steam_id, game["app_id"])

    for attempt in range(config.SLOW_DOWN_RETRIES + 1):
        if attempt:
            yield f"{done}/{len(todo)}, Steam asked us to wait"
            time.sleep(config.SLOW_DOWN_SECONDS * attempt)
        workers = config.ACHIEVEMENT_WORKERS if attempt == 0 else 1
        slowed_down = False
        answers = _a_few_at_a_time(ask, waiting, workers)
        try:
            for game, answer in answers:
                if isinstance(answer, api.PrivateAchievements):
                    return  # private for one game means private for all of them
                if isinstance(answer, api.RateLimited):
                    slowed_down = True
                    break  # closing `answers` cancels the calls that haven't gone out yet
                if isinstance(answer, api.SteamError):
                    if not isinstance(answer, SKIPPABLE):
                        raise answer
                else:
                    # Saved here, on this thread, so only one thread ever writes to the database.
                    storage.save_achievements(steam_id, game["app_id"], game["minutes"], answer)
                waiting.remove(game)
                done += 1
                yield f"{done}/{len(todo)}"
        finally:
            answers.close()
        if not slowed_down:
            return


def check_rarity(steam_id: str):
    """Fetch how rare each achievement is, for games with unlocks whose numbers are missing or old.

    Yields (done, todo) after each game.
    """
    todo = storage.games_needing_rarity(steam_id, time.time() - config.RARITY_REFRESH_DAYS * DAY)
    for done, (app_id, answer) in enumerate(_a_few_at_a_time(api.get_global_percentages, todo), start=1):
        if isinstance(answer, api.RateLimited):
            return
        if isinstance(answer, api.SteamError):
            if not isinstance(answer, SKIPPABLE):
                raise answer
        else:
            storage.save_rarity([(app_id, answer)])
        yield done, len(todo)


def fetch_missing_icons(steam_id: str) -> None:
    """Icons for the achievements achievements.exe is about to show.

    Icons come from a separate call per game, so only the games in the
    "latest unlocks" list (and the rarest unlock's game) are asked about,
    and only until they have them. Missing icons aren't worth failing over:
    the window shows a letter instead.
    """
    shown = storage.get_recent_unlocks(steam_id, config.RECENT_UNLOCKS_COUNT)
    rarest = storage.get_rarest_unlock(steam_id)
    if rarest:
        shown.append(rarest)
    for app_id in {unlock["app_id"] for unlock in shown if not unlock["icon"]}:
        try:
            storage.save_achievement_icons(app_id, api.get_achievement_icons(app_id))
        except api.SteamError:
            continue


def _a_few_at_a_time(ask, items: list, workers: int | None = None):
    """Call ask(item) for every item, `workers` at once (config.ACHIEVEMENT_WORKERS if not given).

    Yields (item, answer) in the order the answers come back. If Steam said
    no, the answer is the SteamError, so the caller decides what it means.
    Stopping early cancels the calls that haven't started yet.
    """
    if not items:
        return
    pool = ThreadPoolExecutor(max_workers=workers or config.ACHIEVEMENT_WORKERS)
    try:
        asked = {pool.submit(ask, item): item for item in items}
        for answer in as_completed(asked):
            try:
                result = answer.result()
            except api.SteamError as error:
                result = error
            yield asked[answer], result
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
