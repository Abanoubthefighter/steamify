"""SQLite storage: what we know about each player, plus the play history.

Steam only ever reports lifetime totals ("812 hours in this game"). It never
says *when* those hours happened. So every time a player is scanned, the new
totals are compared with the ones saved last time and the difference goes
into play_log under today's date. Over days and weeks that log turns into
the history chart.
"""

import sqlite3
import time
from contextlib import contextmanager
from datetime import date

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    steam_id     TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    avatar       TEXT,
    profile_url  TEXT,
    status       TEXT,
    level        INTEGER,
    created      INTEGER,           -- when the Steam account was made (unix time)
    first_seen   INTEGER NOT NULL,  -- our first scan of this player
    synced_at    INTEGER NOT NULL   -- our latest scan
);

-- Names and icons are stored once per game, not once per owner.
CREATE TABLE IF NOT EXISTS games (
    app_id  INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    icon    TEXT
);

-- What each player owns right now. Replaced on every scan.
CREATE TABLE IF NOT EXISTS library (
    steam_id        TEXT    NOT NULL REFERENCES players (steam_id) ON DELETE CASCADE,
    app_id          INTEGER NOT NULL REFERENCES games (app_id),
    minutes         INTEGER NOT NULL,
    minutes_2weeks  INTEGER NOT NULL DEFAULT 0,
    last_played     INTEGER,
    PRIMARY KEY (steam_id, app_id)
) WITHOUT ROWID;

-- The history Steam doesn't keep: minutes gained per game per day.
-- A row only exists if that game's total actually went up, so a normal day
-- adds a handful of rows, not one per game owned. The key starts with
-- (steam_id, day) so "this player, since this date" is one contiguous read.
CREATE TABLE IF NOT EXISTS play_log (
    steam_id  TEXT    NOT NULL REFERENCES players (steam_id) ON DELETE CASCADE,
    day       TEXT    NOT NULL,     -- "2026-11-17"
    app_id    INTEGER NOT NULL REFERENCES games (app_id),
    minutes   INTEGER NOT NULL,
    PRIMARY KEY (steam_id, day, app_id)
) WITHOUT ROWID;

-- Small things to remember between runs, like who was on screen last.
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
) WITHOUT ROWID;
"""

# How much of a day string like "2026-11-17" names each size of bucket.
BUCKET_LENGTH = {"day": 10, "month": 7}


@contextmanager
def open_db():
    """Open the database for one piece of work.

    Used as `with open_db() as db:`. If the block finishes, its changes are
    saved. If it raises, they are all undone, so a scan can never be left
    half-written. Either way the file gets closed again.
    """
    db = sqlite3.connect(config.DATABASE_PATH)
    db.row_factory = sqlite3.Row  # rows can be read by column name
    db.execute("PRAGMA foreign_keys = ON")  # SQLite leaves this off unless asked
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create the database file and its tables if they aren't there yet."""
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open_db() as db:
        # WAL mode lets the page keep reading while a background sync writes.
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(SCHEMA)


# --- Saving a scan -----------------------------------------------------------


def save_snapshot(profile: dict, games: list[dict], now: float | None = None) -> int:
    """Save a fresh scan and log what was played since the previous one.

    Returns the number of minutes added to the play log. That is 0 on a
    player's first scan, because there's nothing to compare against yet.
    """
    now = int(now or time.time())
    today = date.fromtimestamp(now).isoformat()
    steam_id = profile["steam_id"]

    with open_db() as db:
        known = db.execute("SELECT 1 FROM players WHERE steam_id = ?", (steam_id,)).fetchone()
        before = dict(db.execute("SELECT app_id, minutes FROM library WHERE steam_id = ?", (steam_id,)).fetchall())

        played = []
        if known:
            for game in games:
                gained = game["minutes"] - before.get(game["app_id"], 0)
                if gained > 0:
                    played.append((steam_id, today, game["app_id"], gained))

        # ON CONFLICT ... DO UPDATE instead of INSERT OR REPLACE on purpose:
        # REPLACE deletes the old row first, and that would cascade and wipe
        # the player's library and history.
        db.execute(
            """
            INSERT INTO players (steam_id, name, avatar, profile_url, status, level, created, first_seen, synced_at)
            VALUES (:steam_id, :name, :avatar, :profile_url, :status, :level, :created, :now, :now)
            ON CONFLICT (steam_id) DO UPDATE SET
                name = excluded.name, avatar = excluded.avatar, profile_url = excluded.profile_url,
                status = excluded.status, level = excluded.level, created = excluded.created,
                synced_at = excluded.synced_at
            """,
            {**profile, "now": now},
        )
        db.executemany(
            """
            INSERT INTO games (app_id, name, icon) VALUES (:app_id, :name, :icon)
            ON CONFLICT (app_id) DO UPDATE SET name = excluded.name, icon = excluded.icon
            """,
            games,
        )
        db.execute("DELETE FROM library WHERE steam_id = ?", (steam_id,))
        db.executemany(
            """
            INSERT INTO library (steam_id, app_id, minutes, minutes_2weeks, last_played)
            VALUES (:steam_id, :app_id, :minutes, :minutes_2weeks, :last_played)
            """,
            ({**game, "steam_id": steam_id} for game in games),
        )
        _log_playtime(db, played)

    return sum(minutes for *_, minutes in played)


def add_history(steam_id: str, rows: list[tuple[str, int, int]]) -> None:
    """Write (day, app_id, minutes) rows straight into the play log. Used by the demo data."""
    with open_db() as db:
        _log_playtime(db, [(steam_id, day, app_id, minutes) for day, app_id, minutes in rows])


def _log_playtime(db: sqlite3.Connection, rows: list[tuple]) -> None:
    """Add minutes to the log. Two scans on the same day add up instead of clashing."""
    db.executemany(
        """
        INSERT INTO play_log (steam_id, day, app_id, minutes) VALUES (?, ?, ?, ?)
        ON CONFLICT (steam_id, day, app_id) DO UPDATE SET minutes = minutes + excluded.minutes
        """,
        rows,
    )


# --- Reading it back ---------------------------------------------------------


def get_player(steam_id: str) -> dict | None:
    """One saved player, or None if they were never scanned."""
    with open_db() as db:
        row = db.execute("SELECT * FROM players WHERE steam_id = ?", (steam_id,)).fetchone()
    return dict(row) if row else None


def list_players(limit: int) -> list[dict]:
    """The most recently scanned players, newest first."""
    with open_db() as db:
        rows = db.execute(
            "SELECT steam_id, name, avatar FROM players ORDER BY synced_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def forget_player(steam_id: str) -> None:
    """Delete a player. Their library and history go with them (ON DELETE CASCADE)."""
    with open_db() as db:
        db.execute("DELETE FROM players WHERE steam_id = ?", (steam_id,))


def get_library(steam_id: str) -> list[dict]:
    """Every game a player owns, as the dicts the stats functions expect."""
    with open_db() as db:
        rows = db.execute(
            """
            SELECT app_id, name, icon, minutes, minutes_2weeks, last_played
            FROM library JOIN games USING (app_id)
            WHERE steam_id = ?
            """,
            (steam_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_history(steam_id: str, since: str, bucket: str) -> list[dict]:
    """Minutes played per day or per month since a date, with each period's top game.

    Returns rows like {"bucket": "2026-11", "minutes": 1540, "top_game": "Hades"},
    oldest first. Periods with no play at all simply aren't in the list.
    """
    with open_db() as db:
        rows = db.execute(
            """
            WITH per_game AS (      -- minutes per game inside each period
                SELECT substr(day, 1, :length) AS bucket, app_id, SUM(minutes) AS minutes
                FROM play_log
                WHERE steam_id = :steam_id AND day >= :since
                GROUP BY bucket, app_id
            ),
            ranked AS (             -- each period's total, and every game's place in it
                SELECT bucket, app_id,
                       SUM(minutes) OVER (PARTITION BY bucket) AS bucket_minutes,
                       ROW_NUMBER() OVER (PARTITION BY bucket ORDER BY minutes DESC) AS place
                FROM per_game
            )
            SELECT bucket, bucket_minutes AS minutes, name AS top_game
            FROM ranked JOIN games USING (app_id)
            WHERE place = 1
            ORDER BY bucket
            """,
            {"length": BUCKET_LENGTH[bucket], "steam_id": steam_id, "since": since},
        ).fetchall()
    return [dict(row) for row in rows]


def first_log_day(steam_id: str) -> str | None:
    """The earliest day in a player's play log, or None if nothing is logged yet."""
    with open_db() as db:
        return db.execute("SELECT MIN(day) FROM play_log WHERE steam_id = ?", (steam_id,)).fetchone()[0]


def get_shared_games(steam_id: str, friend_id: str, limit: int) -> tuple[list[dict], int]:
    """Games both players own, biggest combined playtime first.

    Returns (the top `limit` games, how many shared games there are in total).
    """
    with open_db() as db:
        rows = db.execute(
            """
            SELECT name,
                   mine.minutes   AS my_minutes,
                   theirs.minutes AS their_minutes,
                   COUNT(*) OVER () AS shared_count   -- counted before LIMIT cuts the list
            FROM library AS mine
            JOIN library AS theirs USING (app_id)
            JOIN games USING (app_id)
            WHERE mine.steam_id = ? AND theirs.steam_id = ?
            ORDER BY mine.minutes + theirs.minutes DESC, name
            LIMIT ?
            """,
            (steam_id, friend_id, limit),
        ).fetchall()
    return [dict(row) for row in rows], (rows[0]["shared_count"] if rows else 0)


# --- Settings ----------------------------------------------------------------


def get_setting(key: str, default: str | None = None) -> str | None:
    with open_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str | None) -> None:
    with open_db() as db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
