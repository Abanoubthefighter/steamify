"""A scan: ask Steam about one player and save what comes back."""

import threading
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

# One scan at a time. Sync now on the page and the hourly background sync
# (background.py) could otherwise save the same player at the same moment.
_one_at_a_time = threading.Lock()


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
    shortcut. Raises api.SteamError if Steam can't or won't answer. If
    another scan is already running, this one waits for it first.
    """
    yield {"label": STEPS[0]}
    if not _one_at_a_time.acquire(blocking=False):
        yield {"detail": "waiting for the scan that's already running"}
        _one_at_a_time.acquire()
    try:
        yield from _scan(query, force)
    finally:
        _one_at_a_time.release()  # also when the page goes away halfway and the scan is dropped


def _scan(query: str, force: bool):
    """The steps of scan() after the first label, while it holds the one-at-a-time lock."""
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

    Steam also answers "Profile is not public" for some games on a perfectly
    public profile (seen on a real one, flagged games included). So that
    answer only means "this game", see _settle_refused. A player only counts
    as private if they never shared a single achievement and keep refusing.
    """
    checked = storage.get_checked_minutes(steam_id)
    todo = games_to_check(games, checked)
    waiting = list(todo)
    done = 0
    refused = []  # games Steam answered "not public" for
    shared = storage.has_shared_achievements(steam_id)  # becomes True as soon as any game answers

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
                if isinstance(answer, api.RateLimited):
                    slowed_down = True
                    break  # closing `answers` cancels the calls that haven't gone out yet
                if isinstance(answer, api.PrivateAchievements):
                    refused.append(game)
                    if not shared and len(refused) >= config.NOT_PUBLIC_GIVE_UP:
                        # Game after game refused, and this player never shared one achievement:
                        # it really is the profile. No point asking about the rest.
                        storage.mark_achievements_private(steam_id)
                        return
                elif isinstance(answer, api.SteamError):
                    if not isinstance(answer, SKIPPABLE):
                        raise answer
                else:
                    shared = True
                    # Saved here, on this thread, so only one thread ever writes to the database.
                    storage.save_achievements(steam_id, game["app_id"], game["minutes"], answer)
                waiting.remove(game)
                done += 1
                yield f"{done}/{len(todo)}"
        finally:
            answers.close()
        if not slowed_down:
            break
    _settle_refused(steam_id, refused, checked, shared)


def _settle_refused(steam_id: str, refused: list[dict], checked: dict[int, int], shared: bool) -> None:
    """What the "not public" answers of one check mean.

    A player who has shared achievements before (or did in this check) isn't
    private: those games just don't show theirs. A refused game that was
    never answered before is saved as checked with none, so it isn't waiting
    forever; one that has saved achievements keeps them. A player who never
    shared any and refused everything this time is remembered as private.
    """
    if not refused:
        return
    if not shared:
        storage.mark_achievements_private(steam_id)
        return
    for game in refused:
        if game["app_id"] not in checked:
            storage.save_achievements(steam_id, game["app_id"], game["minutes"], [])


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
        fetch_icons(app_id)


def fetch_icons(app_id: int) -> None:
    """Fetch one game's achievement icons, unless they're all saved already.

    Used during a scan (above) and when a game is opened in trophies.exe.
    Never raises: without its icon an achievement just shows a letter.
    Demo games have made-up negative IDs, so Steam is never asked about those.
    """
    if app_id <= 0 or not config.STEAM_API_KEY or not storage.is_missing_icons(app_id):
        return
    try:
        storage.save_achievement_icons(app_id, api.get_achievement_icons(app_id))
    except api.SteamError:
        pass


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
