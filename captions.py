"""The words in warning.exe, versus.exe and achievements.exe.

All the jokes live here on purpose, so they're easy to find, edit or delete.
Each *_alert function looks at the numbers and returns one popup, or None
when it has nothing to say.
"""

import time

import config
import stats
from formatting import DAY, hours, plural, year


def _alert(big: str, text: str, caption: str) -> dict:
    """One popup: a big number, what it counts, and a remark underneath."""
    return {"big": big, "text": text, "caption": caption}


DEMO_ALERT = _alert("demo", "this player is made up", "Scan a Steam ID in scan.exe to see a real library.")


def backlog_alert(summary: dict) -> dict | None:
    """How much of the library has never been opened."""
    if summary["game_count"] == 0:
        return None
    never = summary["never_count"]
    if never == 0:
        return _alert("0", "games never launched", "Every single one got opened at least once. Who are you?")

    if never == 1:
        return _alert("1", "game never launched", "Just the one. It can wait a little longer.")

    share = 100 - summary["played_percent"]
    if share >= 50:
        caption = "More than half your library is still in the wrapper."
    elif share >= 25:
        caption = "That's a lot of “I'll get to it eventually”."
    else:
        caption = "Honestly? That's pretty disciplined."
    return _alert(f"{never:,}", "games never launched", caption)


def obsession_alert(summary: dict) -> dict | None:
    """One game eating most of the clock."""
    top = summary["top_game"]
    if not top or summary["top_percent"] < config.OBSESSION_PERCENT:
        return None
    others = summary["game_count"] - 1
    caption = f"The other {plural(others, 'game')} would like a word." if others else "To be fair, it's the only one you own."
    return _alert(f"{summary['top_percent']}%", f"of your playtime is {top['name']}", caption)


def abandoned_alert(games: list[dict], now: float | None = None) -> dict | None:
    """A favourite that hasn't been touched in a long time."""
    cutoff = (now or time.time()) - config.ABANDONED_DAYS * DAY
    for game in stats.top_games(games, config.FAVOURITES_COUNT):
        if game["last_played"] and game["last_played"] < cutoff:
            return _alert(
                hours(game["minutes"]),
                f"in {game['name']}, untouched since {year(game['last_played'])}",
                "You two used to be so close.",
            )
    return None


def fortnight_alert(summary: dict) -> dict | None:
    """Either a very quiet two weeks or a very busy one."""
    if summary["played_count"] == 0:
        return None
    recent = summary["recent_minutes"]
    if recent == 0:
        return _alert("0 h", "played in the last two weeks", "Exam season, or did you go outside?")
    if recent >= config.BINGE_HOURS * 60:
        return _alert(hours(recent), "played in the last two weeks", "That's a part-time job. Steam should be paying you.")
    return None


def lifetime_alert(summary: dict) -> dict | None:
    """All the playtime, counted in whole days."""
    days = summary["total_minutes"] // (60 * 24)
    if days < 1:
        return None
    return _alert(
        f"{days:,}",
        "full day spent on Steam" if days == 1 else "full days spent on Steam",
        f"That's {hours(summary['total_minutes'])}, and it doesn't count the loading screens.",
    )


def build_alerts(games: list[dict], summary: dict, is_demo: bool = False, now: float | None = None) -> list[dict]:
    """Every popup worth showing for this library, most striking first."""
    checks = [
        DEMO_ALERT if is_demo else None,
        backlog_alert(summary),
        obsession_alert(summary),
        abandoned_alert(games, now),
        fortnight_alert(summary),
        lifetime_alert(summary),
    ]
    return [alert for alert in checks if alert][: config.MAX_ALERTS]


def versus_caption(friend_name: str, lead_minutes: int) -> str:
    """The line under the scoreboard in versus.exe. A positive lead means you're ahead."""
    if lead_minutes == 0:
        return "A perfect tie. Suspicious."
    gap = hours(abs(lead_minutes))
    if lead_minutes > 0:
        return f"You're {gap} ahead. Whether that counts as winning is up to you."
    return f"{friend_name} is {gap} ahead. Catch up, or go outside. Your call."


def achievement_caption(summary: dict, percent: int) -> str:
    """The line under the totals in achievements.exe."""
    perfect = summary["perfect"]
    if perfect >= 10:
        return f"{plural(perfect, 'game')} finished down to the last achievement. Completionist, or no life? Both."
    if percent >= 60:
        return "More than half of everything unlocked. The developers thank you personally."
    if perfect:
        return f"{plural(perfect, 'game')} done to 100%. The rest are, let's say, in progress."
    if percent < 15:
        return "You collect games, not achievements."
    return "Plenty unlocked. Plenty more where that came from."


def versus_achievement_caption(friend_name: str, duel: dict) -> str:
    """The line under the achievement duel in versus.exe (see storage.get_shared_achievements)."""
    mine, theirs = duel["my_unlocked"], duel["their_unlocked"]
    my_perfect, their_perfect = duel["my_perfect"], duel["their_perfect"]
    if mine == theirs:
        return "Dead even on achievements. Suspicious, again."
    if mine > theirs and my_perfect < their_perfect:
        return f"More unlocks, fewer finishes. {friend_name} actually sees the credits."
    if mine < theirs and my_perfect > their_perfect:
        return f"{friend_name} unlocks more, but you're the one who finishes games."
    if mine > theirs:
        return f"{plural(mine - theirs, 'achievement')} ahead on the games you share. Rub it in, politely."
    return f"{friend_name} has {plural(theirs - mine, 'achievement')} more on the games you share. Time to grind."
