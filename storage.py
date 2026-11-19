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

-- Achievement totals per player per game, plus how long the game had been
-- played when Steam was last asked. Achievements only unlock while playing,
-- so a game is only asked about again once its playtime has gone up.
CREATE TABLE IF NOT EXISTS achievement_games (
    steam_id         TEXT    NOT NULL REFERENCES players (steam_id) ON DELETE CASCADE,
    app_id           INTEGER NOT NULL REFERENCES games (app_id),
    total            INTEGER NOT NULL,   -- achievements in the game (0: it has none)
    unlocked         INTEGER NOT NULL,
    checked_minutes  INTEGER NOT NULL,   -- the game's playtime when it was checked
    PRIMARY KEY (steam_id, app_id)
) WITHOUT ROWID;

-- Every unlocked achievement. Locked ones aren't stored; "total" above counts them.
CREATE TABLE IF NOT EXISTS unlocks (
    steam_id     TEXT    NOT NULL REFERENCES players (steam_id) ON DELETE CASCADE,
    app_id       INTEGER NOT NULL REFERENCES games (app_id),
    api_name     TEXT    NOT NULL,
    unlocked_at  INTEGER,                -- unix time; NULL for old unlocks Steam has no date for
    PRIMARY KEY (steam_id, app_id, api_name)
) WITHOUT ROWID;

-- Names, icons and rarity, stored once per achievement rather than once per player.
CREATE TABLE IF NOT EXISTS achievement_info (
    app_id       INTEGER NOT NULL REFERENCES games (app_id),
    api_name     TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    icon         TEXT,                   -- picture address, fetched when it's first shown
    percent      REAL,                   -- share of all players who have it
    PRIMARY KEY (app_id, api_name)
) WITHOUT ROWID;

-- When each game's rarity numbers (achievement_info.percent) were last
-- fetched. They barely move, so they're only fetched again after a while.
CREATE TABLE IF NOT EXISTS rarity_checked (
    app_id      INTEGER PRIMARY KEY,
    checked_at  INTEGER NOT NULL
);

-- Players whose achievements Steam wouldn't share at their latest scan.
-- A row goes away again as soon as Steam answers for one of their games.
CREATE TABLE IF NOT EXISTS private_achievements (
    steam_id    TEXT PRIMARY KEY REFERENCES players (steam_id) ON DELETE CASCADE,
    noticed_at  INTEGER NOT NULL
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


def players_synced_before(timestamp: float) -> list[str]:
    """Steam IDs of the players last scanned before this moment, the longest ago first."""
    with open_db() as db:
        rows = db.execute(
            "SELECT steam_id FROM players WHERE synced_at < ? ORDER BY synced_at", (int(timestamp),)
        ).fetchall()
    return [row["steam_id"] for row in rows]


def forget_player(steam_id: str) -> None:
    """Delete a player. Their library, history and achievements go with them (ON DELETE CASCADE)."""
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


# --- Achievements --------------------------------------------------------------


def get_checked_minutes(steam_id: str) -> dict[int, int]:
    """For every game whose achievements were checked: its playtime at the time. {app_id: minutes}"""
    with open_db() as db:
        rows = db.execute(
            "SELECT app_id, checked_minutes FROM achievement_games WHERE steam_id = ?", (steam_id,)
        ).fetchall()
    return dict(rows)


def save_achievements(steam_id: str, app_id: int, minutes: int, achievements: list[dict]) -> None:
    """Save one game's achievements for one player, as api.get_achievements returns them.

    An empty list is saved too: it records "this game has none", so the
    game isn't asked about again until it's played some more.
    """
    with open_db() as db:
        _write_achievements(db, steam_id, app_id, minutes, achievements)


def save_many_achievements(steam_id: str, checked: list[tuple[int, int, list[dict]]]) -> None:
    """save_achievements for many games at once, as (app_id, minutes, achievements), in one go."""
    with open_db() as db:
        for app_id, minutes, achievements in checked:
            _write_achievements(db, steam_id, app_id, minutes, achievements)


def _write_achievements(db: sqlite3.Connection, steam_id: str, app_id: int, minutes: int, achievements: list[dict]) -> None:
    unlocked = [item for item in achievements if item["achieved"]]
    db.execute(
        """
        INSERT INTO achievement_games (steam_id, app_id, total, unlocked, checked_minutes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (steam_id, app_id) DO UPDATE SET
            total = excluded.total, unlocked = excluded.unlocked, checked_minutes = excluded.checked_minutes
        """,
        (steam_id, app_id, len(achievements), len(unlocked), minutes),
    )
    # Steam always sends a game's full list, so anything not in it was removed
    # from the game (or is left over from an older demo). An empty list is left
    # alone: that's "this game has none", nothing to compare against.
    if achievements:
        names = [item["api_name"] for item in achievements]
        db.execute(
            f"DELETE FROM achievement_info WHERE app_id = ? AND api_name NOT IN ({', '.join('?' * len(names))})",
            (app_id, *names),
        )
    # Keep any icon or rarity already known; only the words can change.
    db.executemany(
        """
        INSERT INTO achievement_info (app_id, api_name, name, description)
        VALUES (:app_id, :api_name, :name, :description)
        ON CONFLICT (app_id, api_name) DO UPDATE SET name = excluded.name, description = excluded.description
        """,
        ({**item, "app_id": app_id} for item in achievements),
    )
    db.execute("DELETE FROM unlocks WHERE steam_id = ? AND app_id = ?", (steam_id, app_id))
    db.execute("DELETE FROM private_achievements WHERE steam_id = ?", (steam_id,))  # Steam shared them, so they aren't private
    db.executemany(
        "INSERT INTO unlocks (steam_id, app_id, api_name, unlocked_at) VALUES (?, ?, ?, ?)",
        ((steam_id, app_id, item["api_name"], item["unlocked_at"]) for item in unlocked),
    )


def save_achievement_icons(app_id: int, icons: dict[str, str]) -> None:
    """Remember icon addresses, {api name: address}, for a game's achievements."""
    with open_db() as db:
        db.executemany(
            "UPDATE achievement_info SET icon = ? WHERE app_id = ? AND api_name = ?",
            ((icon, app_id, api_name) for api_name, icon in icons.items()),
        )


def is_missing_icons(app_id: int) -> bool:
    """True if any of a game's known achievements has no icon address saved yet."""
    with open_db() as db:
        row = db.execute("SELECT 1 FROM achievement_info WHERE app_id = ? AND icon IS NULL LIMIT 1", (app_id,)).fetchone()
    return row is not None


def move_icon_addresses(new_address) -> int:
    """Rewrite saved icon addresses with new_address(app_id, address). Returns how many changed.

    For when Steam moves its pictures (see api.achievement_icon_address).
    Addresses that are already right are left alone, so this is quick to
    run at every start.
    """
    with open_db() as db:
        rows = db.execute("SELECT app_id, api_name, icon FROM achievement_info WHERE icon IS NOT NULL").fetchall()
        moved = []
        for row in rows:
            address = new_address(row["app_id"], row["icon"])
            if address and address != row["icon"]:
                moved.append((address, row["app_id"], row["api_name"]))
        db.executemany("UPDATE achievement_info SET icon = ? WHERE app_id = ? AND api_name = ?", moved)
    return len(moved)


def games_needing_rarity(steam_id: str, checked_before: float) -> list[int]:
    """Games where the player has unlocked something and the rarity is unknown or older than `checked_before`."""
    with open_db() as db:
        rows = db.execute(
            """
            SELECT DISTINCT u.app_id
            FROM unlocks AS u
            JOIN library AS l ON l.steam_id = u.steam_id AND l.app_id = u.app_id
            LEFT JOIN rarity_checked AS r ON r.app_id = u.app_id
            WHERE u.steam_id = ? AND (r.checked_at IS NULL OR r.checked_at < ?)
            """,
            (steam_id, int(checked_before)),
        ).fetchall()
    return [row[0] for row in rows]


def save_rarity(checked: list[tuple[int, dict[str, float]]], now: float | None = None) -> None:
    """Save rarity for some games: [(app_id, {api name: percent of players}), ...]."""
    now = int(now or time.time())
    with open_db() as db:
        for app_id, percents in checked:
            db.executemany(
                "UPDATE achievement_info SET percent = ? WHERE app_id = ? AND api_name = ?",
                ((percent, app_id, api_name) for api_name, percent in percents.items()),
            )
            db.execute(
                """
                INSERT INTO rarity_checked (app_id, checked_at) VALUES (?, ?)
                ON CONFLICT (app_id) DO UPDATE SET checked_at = excluded.checked_at
                """,
                (app_id, now),
            )


def get_rarest_unlock(steam_id: str) -> dict | None:
    """The unlocked achievement the smallest share of players has, or None if no rarity is known yet."""
    with open_db() as db:
        row = db.execute(
            """
            SELECT u.app_id, u.api_name, i.name, i.description, i.icon, i.percent, g.name AS game
            FROM unlocks AS u
            JOIN achievement_info AS i ON i.app_id = u.app_id AND i.api_name = u.api_name
            JOIN games AS g ON g.app_id = u.app_id
            JOIN library AS l ON l.steam_id = u.steam_id AND l.app_id = u.app_id
            WHERE u.steam_id = ? AND i.percent IS NOT NULL
            ORDER BY i.percent, i.name
            LIMIT 1
            """,
            (steam_id,),
        ).fetchone()
    return dict(row) if row else None


def get_achievement_summary(steam_id: str) -> dict:
    """Achievement totals over the games a player owns right now.

    {"unlocked", "total", "games" (with achievements), "perfect" (every
    achievement unlocked), "checked" (games looked at so far)}
    """
    with open_db() as db:
        row = db.execute(
            """
            SELECT COALESCE(SUM(a.unlocked), 0)                       AS unlocked,
                   COALESCE(SUM(a.total), 0)                          AS total,
                   COUNT(*) FILTER (WHERE a.total > 0)                AS games,
                   COUNT(*) FILTER (WHERE a.total > 0 AND a.unlocked = a.total) AS perfect,
                   COUNT(*)                                           AS checked
            FROM achievement_games AS a
            -- only games still in the library count (not ones refunded since)
            JOIN library AS l ON l.steam_id = a.steam_id AND l.app_id = a.app_id
            WHERE a.steam_id = ?
            """,
            (steam_id,),
        ).fetchone()
    return dict(row)


def get_achievement_coverage(steam_id: str) -> dict:
    """How complete a player's achievement numbers are.

    {"played": games played at all, "waiting": played games never checked
    yet, "private": True if Steam wouldn't share them at the latest scan}
    """
    with open_db() as db:
        row = db.execute(
            """
            SELECT COUNT(*)                                AS played,
                   COUNT(*) FILTER (WHERE a.app_id IS NULL) AS waiting,
                   EXISTS (SELECT 1 FROM private_achievements WHERE steam_id = :id) AS private
            FROM library AS l
            LEFT JOIN achievement_games AS a ON a.steam_id = l.steam_id AND a.app_id = l.app_id
            WHERE l.steam_id = :id AND l.minutes > 0
            """,
            {"id": steam_id},
        ).fetchone()
    return {**dict(row), "private": bool(row["private"])}


def has_shared_achievements(steam_id: str) -> bool:
    """True if Steam ever answered with achievements for this player (any game that has some)."""
    with open_db() as db:
        row = db.execute("SELECT 1 FROM achievement_games WHERE steam_id = ? AND total > 0 LIMIT 1", (steam_id,)).fetchone()
    return row is not None


def mark_achievements_private(steam_id: str, now: float | None = None) -> None:
    """Remember that Steam wouldn't share this player's achievements.

    Saving any of their achievements later (save_achievements) clears it again.
    """
    with open_db() as db:
        db.execute(
            "INSERT INTO private_achievements (steam_id, noticed_at) VALUES (?, ?) ON CONFLICT (steam_id) DO NOTHING",
            (steam_id, int(now or time.time())),
        )


def get_recent_unlocks(steam_id: str, limit: int) -> list[dict]:
    """The latest achievements a player unlocked, newest first, with their game."""
    with open_db() as db:
        rows = db.execute(
            """
            SELECT u.app_id, u.api_name, u.unlocked_at, i.name, i.description, i.icon, g.name AS game
            FROM unlocks AS u
            JOIN achievement_info AS i ON i.app_id = u.app_id AND i.api_name = u.api_name
            JOIN games AS g ON g.app_id = u.app_id
            JOIN library AS l ON l.steam_id = u.steam_id AND l.app_id = u.app_id
            WHERE u.steam_id = ? AND u.unlocked_at IS NOT NULL
            ORDER BY u.unlocked_at DESC
            LIMIT ?
            """,
            (steam_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_nearly_done(steam_id: str, at_least_percent: int, limit: int) -> list[dict]:
    """Games with most, but not all, of their achievements unlocked. Closest to done first."""
    with open_db() as db:
        rows = db.execute(
            """
            SELECT a.app_id, g.name, a.unlocked, a.total
            FROM achievement_games AS a
            JOIN games AS g ON g.app_id = a.app_id
            JOIN library AS l ON l.steam_id = a.steam_id AND l.app_id = a.app_id
            WHERE a.steam_id = ? AND a.total > 0 AND a.unlocked < a.total
              AND a.unlocked * 100 >= a.total * ?
            ORDER BY a.unlocked * 1.0 / a.total DESC, a.total - a.unlocked, g.name
            LIMIT ?
            """,
            (steam_id, at_least_percent, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_achievement_games(steam_id: str) -> list[dict]:
    """Every owned game with achievements, for trophies.exe.

    Each is {"app_id", "name", "icon", "unlocked", "total", "last_unlock"};
    last_unlock is the newest dated unlock (unix time), or None.
    """
    with open_db() as db:
        rows = db.execute(
            """
            SELECT a.app_id, g.name, g.icon, a.unlocked, a.total,
                   (SELECT MAX(u.unlocked_at) FROM unlocks AS u
                    WHERE u.steam_id = a.steam_id AND u.app_id = a.app_id) AS last_unlock
            FROM achievement_games AS a
            JOIN games AS g ON g.app_id = a.app_id
            JOIN library AS l ON l.steam_id = a.steam_id AND l.app_id = a.app_id
            WHERE a.steam_id = ? AND a.total > 0
            """,
            (steam_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_game_achievements(steam_id: str, app_id: int) -> list[dict]:
    """Every achievement in one game, unlocked or not, for the game's page in trophies.exe.

    Unlocked ones come first, newest first. Then the locked ones, the most
    common first: those are the ones most players manage, so probably the
    easiest to get next. Each has "achieved" (True/False) and "unlocked_at".
    """
    with open_db() as db:
        rows = db.execute(
            """
            SELECT i.api_name, i.name, i.description, i.icon, i.percent, u.unlocked_at,
                   u.api_name IS NOT NULL AS achieved
            FROM achievement_info AS i
            LEFT JOIN unlocks AS u ON u.app_id = i.app_id AND u.api_name = i.api_name AND u.steam_id = ?
            WHERE i.app_id = ?
            ORDER BY achieved DESC, u.unlocked_at IS NULL, u.unlocked_at DESC,
                     i.percent IS NULL, i.percent DESC, i.name
            """,
            (steam_id, app_id),
        ).fetchall()
    return [{**dict(row), "achieved": bool(row["achieved"])} for row in rows]


def get_unlock_counts(steam_id: str, bucket: str, since: str = "") -> list[dict]:
    """How many achievements were unlocked per month ("2026-11") or year ("2026").

    [{"bucket": "2026-10", "unlocks": 12}, ...], oldest first, only periods
    with unlocks, from `since` on (same text as the buckets). Undated unlocks
    are left out. Steam dates every unlock, so this goes back further than
    the play log, which only starts with the first scan.
    """
    pattern = {"month": "%Y-%m", "year": "%Y"}[bucket]
    with open_db() as db:
        rows = db.execute(
            """
            SELECT strftime(?, u.unlocked_at, 'unixepoch', 'localtime') AS bucket, COUNT(*) AS unlocks
            FROM unlocks AS u
            JOIN library AS l ON l.steam_id = u.steam_id AND l.app_id = u.app_id
            WHERE u.steam_id = ? AND u.unlocked_at IS NOT NULL
            GROUP BY bucket
            HAVING bucket >= ?
            ORDER BY bucket
            """,
            (pattern, steam_id, since),
        ).fetchall()
    return [dict(row) for row in rows]


def get_shared_achievements(steam_id: str, friend_id: str) -> dict:
    """Achievement totals for two players, over the games with achievements they both own.

    {"games", "my_unlocked", "their_unlocked", "my_perfect", "their_perfect"}
    """
    with open_db() as db:
        row = db.execute(
            """
            SELECT COUNT(*)                                                 AS games,
                   COALESCE(SUM(mine.unlocked), 0)                          AS my_unlocked,
                   COALESCE(SUM(theirs.unlocked), 0)                        AS their_unlocked,
                   COUNT(*) FILTER (WHERE mine.unlocked = mine.total)       AS my_perfect,
                   COUNT(*) FILTER (WHERE theirs.unlocked = theirs.total)   AS their_perfect
            FROM achievement_games AS mine
            JOIN achievement_games AS theirs ON theirs.app_id = mine.app_id
            JOIN library AS my_copy ON my_copy.steam_id = mine.steam_id AND my_copy.app_id = mine.app_id
            JOIN library AS their_copy ON their_copy.steam_id = theirs.steam_id AND their_copy.app_id = theirs.app_id
            WHERE mine.steam_id = ? AND theirs.steam_id = ? AND mine.total > 0 AND theirs.total > 0
            """,
            (steam_id, friend_id),
        ).fetchone()
    return dict(row)


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
