"""Syncing on a timer while the desktop app is open, in the window or in the tray.

Every few minutes (config.BACKGROUND_CHECK_MINUTES) a background thread
looks for saved players whose last scan is older than
config.BACKGROUND_SYNC_MINUTES, and scans them one after another, exactly
like Sync now does. That way the playtime history fills in on its own, even
when nobody opens the window for days.

It needs a Steam API key, skips the demo players, and can be switched off
in settings.exe. When Steam can't be reached, it tries again next time
instead of showing popups. "Sync now" in the tray menu runs a round straight
away, for everyone.
"""

import json
import logging
import threading
import time

import api
import config
import demo
import preferences
import storage
import sync

LAST_RUN = "background_sync_last"  # setting: what the latest round did, for sync.exe

log = logging.getLogger(__name__)


def players_due(now: float) -> list[str]:
    """The saved players (not the demo) whose last scan is older than the sync interval."""
    return _real_players(scanned_before=now - config.BACKGROUND_SYNC_MINUTES * 60)


def _real_players(scanned_before: float) -> list[str]:
    return [steam_id for steam_id in storage.players_synced_before(scanned_before) if not demo.is_demo(steam_id)]


def sync_round(everyone: bool = False, failed_at: dict | None = None, now: float | None = None) -> dict | None:
    """Scan every player who's due (`everyone`: every saved player), one at a time.

    `failed_at` remembers when each player last failed ({steam_id: time}),
    so a profile that went private isn't asked about every few minutes: it
    waits a whole interval, like everyone else. Returns what happened,
    {"at", "synced", "failed", "problem"}, and saves it for sync.exe. Returns
    None if there was nothing to do: no key, switched off, or nobody due.
    """
    now = now or time.time()
    failed_at = {} if failed_at is None else failed_at
    if not config.STEAM_API_KEY or not (everyone or preferences.background_sync()):
        return None
    if everyone:
        players = _real_players(scanned_before=now + 1)
    else:
        wait = config.BACKGROUND_SYNC_MINUTES * 60
        players = [steam_id for steam_id in players_due(now) if now - failed_at.get(steam_id, 0) >= wait]
    if not players:
        return None

    synced, failed, problem = 0, 0, None
    for steam_id in players:
        try:
            for _ in sync.scan(steam_id, force=True):
                pass  # the progress events are for the page; here only the end matters
            synced += 1
            failed_at.pop(steam_id, None)
        except api.SteamError as error:
            failed += 1
            failed_at[steam_id] = now
            problem = error.title
            log.warning("Background sync of %s failed: %s", steam_id, error.title)
        except Exception:
            failed += 1
            failed_at[steam_id] = now
            problem = "Something went wrong"
            log.exception("Background sync of %s failed", steam_id)

    result = {"at": int(now), "synced": synced, "failed": failed, "problem": problem}
    storage.set_setting(LAST_RUN, json.dumps(result))
    return result


def last_round() -> dict | None:
    """What the latest background round did (see sync_round), or None if there hasn't been one."""
    try:
        saved = json.loads(storage.get_setting(LAST_RUN) or "null")
    except ValueError:
        return None
    return saved if isinstance(saved, dict) and isinstance(saved.get("at"), int) else None


class BackgroundSync:
    """The thread that runs sync_round now and then. desktop.py starts it."""

    def __init__(self):
        self._wake = threading.Event()
        self._everyone = False  # set by sync_now() for the next round
        self._failed_at = {}    # see sync_round

    def start(self) -> None:
        # A daemon thread: it stops by itself when the app quits, even halfway through a round.
        threading.Thread(target=self._run, daemon=True, name="background-sync").start()

    def sync_now(self) -> None:
        """Run a round for every saved player straight away (the tray's "Sync now")."""
        self._everyone = True
        self._wake.set()

    def _run(self) -> None:
        while True:
            # Wait first: right after start the page refreshes the player on screen anyway.
            self._wake.wait(config.BACKGROUND_CHECK_MINUTES * 60)
            self._wake.clear()
            everyone, self._everyone = self._everyone, False
            try:
                sync_round(everyone=everyone, failed_at=self._failed_at)
            except Exception:  # never let one bad round end the thread
                log.exception("Background sync round failed")
