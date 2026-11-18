"""Badges for keeping the app running, like the ones Discord gives for time on Nitro.

The desktop app adds up how long it has been open, in the window or hidden
in the tray (RunningClock, started by desktop.py). The total is one number in
the settings table. The badges are just thresholds on it, from config.BADGES:
Dial-up at 6 hours, up to Hard drive at 75.

Time the computer spends asleep doesn't count: each tick adds at most one
tick's worth, however long it really was since the last one.
"""

import logging
import threading
import time

import config
import storage

RUNNING = "running_seconds"  # setting: seconds the app has been running, all time
SEEN = "badge_seen"          # setting: the newest badge the "new badge" popup has shown

log = logging.getLogger(__name__)


# --- The running total ----------------------------------------------------------


def running_seconds() -> int:
    try:
        return max(0, int(storage.get_setting(RUNNING) or 0))
    except ValueError:  # a broken value starts the count again rather than breaking the page
        return 0


def add_running(seconds: float) -> tuple[int, int]:
    """Add to the running total. Returns (before, after)."""
    before = running_seconds()
    after = before + max(0, int(seconds))
    storage.set_setting(RUNNING, str(after))
    return before, after


# --- Working out the badges --------------------------------------------------------


def ladder(seconds: int) -> list[dict]:
    """Every badge, smallest first: {"key", "name", "hours", "earned"}."""
    return [
        {"key": key, "name": name, "hours": hours, "earned": seconds >= hours * 3600}
        for key, name, hours in config.BADGES
    ]


def current(seconds: int) -> dict | None:
    """The biggest badge earned so far, or None before the first one."""
    earned = [badge for badge in ladder(seconds) if badge["earned"]]
    return earned[-1] if earned else None


def next_up(seconds: int) -> dict | None:
    """The next badge to earn, with how far along it is, or None once they're all earned.

    {"key", "name", "hours", "earned": False, "minutes_left", "percent"}. The
    percent counts from the badge before it, so each step starts at 0.
    """
    badges = ladder(seconds)
    for index, badge in enumerate(badges):
        if not badge["earned"]:
            start = badges[index - 1]["hours"] * 3600 if index else 0
            end = badge["hours"] * 3600
            return {
                **badge,
                "minutes_left": -(-(end - seconds) // 60),  # rounded up, so it never says 0 min too early
                "percent": round(100 * (seconds - start) / (end - start)),
            }
    return None


def newly_earned(before: int, after: int) -> list[dict]:
    """The badges earned somewhere between two running totals."""
    return [badge for badge in ladder(after) if badge["earned"] and before < badge["hours"] * 3600]


def unseen() -> dict | None:
    """The current badge, if the "new badge" popup hasn't shown it yet."""
    badge = current(running_seconds())
    return badge if badge and storage.get_setting(SEEN) != badge["key"] else None


def mark_seen(key: str) -> None:
    if key in {badge_key for badge_key, _, _ in config.BADGES}:
        storage.set_setting(SEEN, key)


# --- Counting while the app runs ---------------------------------------------------


class RunningClock:
    """A thread that adds the running time up every config.RUNNING_TICK_SECONDS.

    `on_badge(badge)` runs whenever a tick earns a badge (desktop.py shows a
    Windows notice from the tray icon). stop() adds the last part-minute on
    the way out.
    """

    def __init__(self, on_badge=None, clock=time.time):
        self._on_badge = on_badge
        self._clock = clock
        self._stopping = threading.Event()
        self._lock = threading.Lock()  # stop() and the thread could otherwise add the same minute twice
        self._last = None

    def start(self) -> None:
        self._last = self._clock()
        threading.Thread(target=self._run, daemon=True, name="running-clock").start()

    def stop(self) -> None:
        self._stopping.set()
        self.tick()

    def tick(self) -> None:
        """Add the time since the last tick, but never more than one tick's worth.

        A computer that slept for an hour wakes up to a tick that's an hour
        late. Counting only one tick of it is what keeps sleep out of the total.
        """
        with self._lock:
            if self._last is None:
                return
            now = self._clock()
            elapsed = min(max(0.0, now - self._last), config.RUNNING_TICK_SECONDS)
            self._last = now
            before, after = add_running(elapsed)
        for badge in newly_earned(before, after):
            if self._on_badge:
                self._on_badge(badge)

    def _run(self) -> None:
        while not self._stopping.wait(config.RUNNING_TICK_SECONDS):
            try:
                self.tick()
            except Exception:  # a database hiccup shouldn't stop the clock for good
                log.exception("Couldn't add up the running time")
