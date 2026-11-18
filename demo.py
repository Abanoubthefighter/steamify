"""A made-up player, so the app has something to show before there's an API key.

Nothing here touches the network. The numbers come from a random generator
with a fixed seed, so the demo looks the same on every run (handy for
screenshots) while its history always ends today.
"""

import random
import time
from datetime import date, datetime, timedelta

import storage
import sync
from formatting import DAY

PLAYER_ID = "demo"
FRIEND_ID = "demo-friend"

SEED = 8  # picked because its library lands close to the numbers in ui-sample.html
STEP_DELAY = 0.4  # seconds each pretend sync step takes, so the progress bar can be seen moving

PLAYER = {
    "steam_id": PLAYER_ID,
    "name": "player_one",
    "avatar": None,
    "profile_url": None,
    "status": "Online",
    "level": 24,
    "created": 1489500000,  # March 2017
}
FRIEND = {**PLAYER, "steam_id": FRIEND_ID, "name": "player_two", "status": "Away", "level": 17, "created": 1561900000}

# Games the demo player really plays: (name, hours already on the clock before the history starts).
FAVOURITES = [
    ("Counter-Strike 2", 690),
    ("Elden Ring", 250),
    ("Cyberpunk 2077", 150),
    ("Terraria", 131),
    ("Baldur's Gate 3", 0),
    ("Stardew Valley", 64),
    ("Deep Rock Galactic", 58),
    ("Sifu", 80),
    ("Hollow Knight", 31),
    ("Slay the Spire", 44),
    ("Hades", 38),
    ("Balatro", 0),
    ("Celeste", 14),
]

# The demo player's last year, oldest first. Each phase is
# (how many days it lasts, [(game, chance of playing on a given day, typical minutes per session)]).
PHASES = [
    (58, [("Baldur's Gate 3", 0.70, 150)]),
    (30, [("Stardew Valley", 0.55, 85)]),
    (48, [("Elden Ring", 0.75, 140)]),
    (21, [("Sifu", 0.60, 70)]),
    (44, [("Cyberpunk 2077", 0.65, 130)]),
    (30, [("Hollow Knight", 0.50, 90)]),
    (33, [("Slay the Spire", 0.35, 55)]),  # a quiet stretch
    (30, [("Deep Rock Galactic", 0.60, 110)]),
    (26, [("Balatro", 0.65, 75)]),
    (31, [("Terraria", 0.70, 115), ("Celeste", 0.15, 45)]),
    (14, [("Hades", 0.50, 65), ("Terraria", 0.30, 70), ("Celeste", 0.30, 45)]),
]
EVERGREEN = ("Counter-Strike 2", 0.22, 90)  # gets played a little all year round
WEEKEND_BOOST = 1.3

# Everything else in the library: sale purchases, bundles and good intentions.
SHELF = [
    "Portal 2", "Half-Life 2", "Left 4 Dead 2", "Team Fortress 2", "Garry's Mod", "Dota 2",
    "The Witcher 3: Wild Hunt", "Rocket League", "Among Us", "Disco Elysium", "Factorio", "RimWorld",
    "Sid Meier's Civilization VI", "The Elder Scrolls V: Skyrim Special Edition", "Red Dead Redemption 2",
    "Grand Theft Auto V", "DARK SOULS III", "Sekiro: Shadows Die Twice", "Vampire Survivors", "Lethal Company",
    "Cuphead", "Undertale", "Outer Wilds", "Subnautica", "Don't Starve Together", "Dead Cells",
    "Ori and the Blind Forest", "Ori and the Will of the Wisps", "Inscryption", "Return of the Obra Dinn",
    "Papers, Please", "Firewatch", "What Remains of Edith Finch", "It Takes Two", "A Short Hike", "Katana ZERO",
    "Hotline Miami", "Hyper Light Drifter", "Enter the Gungeon", "The Binding of Isaac: Rebirth", "Risk of Rain 2",
    "Monster Hunter: World", "NieR:Automata", "Persona 5 Royal", "DOOM Eternal", "Titanfall 2", "Apex Legends",
    "Rust", "Valheim", "Satisfactory", "Cities: Skylines", "Euro Truck Simulator 2", "Kerbal Space Program",
    "No Man's Sky", "Stellaris", "XCOM 2", "Into the Breach", "FTL: Faster Than Light", "Oxygen Not Included",
    "Noita", "TUNIC", "Sea of Stars", "Dave the Diver", "Hi-Fi RUSH", "Lies of P", "Resident Evil 4",
    "Death Stranding", "Horizon Zero Dawn", "God of War", "Hogwarts Legacy", "Palworld", "Phasmophobia",
    "Fall Guys", "Stray", "Cult of the Lamb", "Neon White", "Pizza Tower", "Loop Hero", "Unpacking",
    "PowerWash Simulator", "Dorfromantik", "Wingspan", "Portal", "BioShock Infinite", "Borderlands 2",
    "Fallout: New Vegas", "Fallout 4", "Dishonored", "Prey", "Control", "Max Payne 3", "Sleeping Dogs",
    "Mirror's Edge", "Psychonauts 2", "Spiritfarer", "GRIS", "LIMBO", "INSIDE", "Little Nightmares",
    "Overcooked! 2", "Human Fall Flat", "Gang Beasts", "Golf With Your Friends",
    "Keep Talking and Nobody Explodes", "Tabletop Simulator", "Raft", "The Forest", "Slime Rancher", "Astroneer",
    "Two Point Hospital", "Frostpunk", "This War of Mine", "Darkest Dungeon", "Divinity: Original Sin 2",
    "Age of Empires II: Definitive Edition", "Crusader Kings III", "Metro Exodus", "Tomb Raider", "Just Cause 3",
    "Assetto Corsa", "BeamNG.drive", "Cookie Clicker", "Brotato", "Dredge",
]  # fmt: skip


# Names for the made-up achievements. Real ones come from Steam, with each game's own.
ACHIEVEMENT_NAMES = [
    "First Steps", "Getting Warmer", "No Turning Back", "Night Owl", "One More Run", "Explorer",
    "Hoarder", "Untouchable", "Speed Demon", "Pacifist", "Collector", "Survivor", "Lucky Break",
    "Iron Will", "Big Spender", "Unstoppable", "Know-It-All", "Close Call", "Overachiever", "The Long Way Round",
]
# Achievements get their own random numbers, so adding them didn't change the demo library.
ACHIEVEMENT_SEED = SEED + 1


def is_demo(steam_id: str) -> bool:
    return steam_id in (PLAYER_ID, FRIEND_ID)


def install(force: bool = False) -> None:
    """Put the demo players in the database.

    Does nothing if they were already loaded today. On a new day it rebuilds
    them, so the invented history always runs right up to the present.
    """
    today = date.today()
    saved = storage.get_player(PLAYER_ID)
    if saved and not force and date.fromtimestamp(saved["synced_at"]) == today:
        return

    rng = random.Random(SEED)
    games, history = _player_library(rng, today)
    first_scan = time.time() - _history_days() * DAY

    for steam_id in (PLAYER_ID, FRIEND_ID):
        storage.forget_player(steam_id)
    # Same order a real player's data builds up in: a first scan a year back,
    # then the play log, then today's scan.
    storage.save_snapshot(PLAYER, games, now=first_scan)
    storage.add_history(PLAYER_ID, history)
    storage.save_snapshot(PLAYER, games)
    friend_games = _friend_library(rng, games)
    storage.save_snapshot(FRIEND, friend_games)

    unlock_rng = random.Random(ACHIEVEMENT_SEED)
    with_achievements = set()
    for steam_id, owned in ((PLAYER_ID, games), (FRIEND_ID, friend_games)):
        minutes = {game["app_id"]: game["minutes"] for game in owned}
        invented = _invent_achievements(unlock_rng, owned, first_scan)
        storage.save_many_achievements(
            steam_id, [(app_id, minutes[app_id], achievements) for app_id, achievements in invented.items()]
        )
        with_achievements.update(invented)
    storage.save_rarity(_invent_rarity(unlock_rng, sorted(with_achievements)))


def scan(query: str, force: bool = False):
    """A pretend scan with the same steps as sync.scan, so the sync window can be tried without a key."""
    for label in sync.STEPS:
        yield {"label": label}
        time.sleep(STEP_DELAY)
    install(force=True)
    yield {"steam_id": query, "gained": 0}


# --- Making things up --------------------------------------------------------


def _history_days() -> int:
    return sum(days for days, _ in PHASES)


def _app_ids() -> dict[str, int]:
    """Demo games get negative IDs, so they can never collide with a real Steam app."""
    names = [name for name, _ in FAVOURITES] + SHELF
    return {name: -(index + 1) for index, name in enumerate(names)}


def _invent_sessions(rng: random.Random, today: date) -> dict[tuple[date, str], int]:
    """Make up a year of play sessions: {(day, game name): minutes}."""
    sessions = {}
    day = today - timedelta(days=_history_days() - 1)
    for days, lineup in PHASES:
        for _ in range(days):
            boost = WEEKEND_BOOST if day.weekday() >= 5 else 1.0
            for name, chance, typical in [*lineup, EVERGREEN]:
                if rng.random() < chance * boost:
                    sessions[(day, name)] = max(20, round(rng.gauss(typical, typical * 0.35)))
            day += timedelta(days=1)
    return sessions


def _shelf_minutes(rng: random.Random) -> int:
    """Most games on the shelf were barely touched. A few got a proper go."""
    roll = rng.random()
    if roll < 0.34:
        return 0  # never launched
    if roll < 0.58:
        return rng.randint(8, 59)  # tried it once
    if roll < 0.92:
        return rng.randint(60, 600)  # an evening or a weekend
    return rng.randint(600, 1800)  # actually finished it


def _evening(day: date) -> int:
    """A unix time on the evening of that day (but never in the future)."""
    return int(min(datetime(day.year, day.month, day.day, 21, 30).timestamp(), time.time()))


def _player_library(rng: random.Random, today: date) -> tuple[list[dict], list[tuple]]:
    """The demo player's games, and the play log rows that explain their recent hours."""
    ids = _app_ids()
    sessions = _invent_sessions(rng, today)
    fortnight_ago = today - timedelta(days=13)

    games = []
    for name, hours_before in FAVOURITES:
        mine = {day: minutes for (day, game), minutes in sessions.items() if game == name}
        games.append(
            {
                "app_id": ids[name],
                "name": name,
                "icon": None,
                "minutes": hours_before * 60 + sum(mine.values()),
                "minutes_2weeks": sum(minutes for day, minutes in mine.items() if day >= fortnight_ago),
                "last_played": _evening(max(mine)) if mine else None,
            }
        )
    for name in SHELF:
        minutes = _shelf_minutes(rng)
        dusty = today - timedelta(days=rng.randint(400, 1500))
        games.append(
            {
                "app_id": ids[name],
                "name": name,
                "icon": None,
                "minutes": minutes,
                "minutes_2weeks": 0,
                "last_played": _evening(dusty) if minutes else None,
            }
        )

    history = [(day.isoformat(), ids[name], minutes) for (day, name), minutes in sessions.items()]
    return games, history


def _invent_achievements(rng: random.Random, games: list[dict], since: float) -> dict[int, list[dict]]:
    """Made-up achievements for the played games: {app_id: [achievement, ...]}.

    The more a game was played, the more of its achievements are done, and
    they were unlocked between `since` and the last time it was played.
    About one game in four has none at all, like on real Steam.
    """
    invented = {}
    for game in games:
        if not game["minutes"] or rng.random() < 0.25:
            continue
        total = rng.randint(12, 60)
        done = round(total * min(1.0, game["minutes"] / 60 / rng.uniform(15, 120)))
        # A favourite with 150 hours or more is finished. Other well-played games
        # often stop just short: those last few achievements are always the hard ones.
        if done == total and game["minutes"] < 150 * 60 and rng.random() < 0.5:
            done -= rng.randint(1, 3)
        last = game["last_played"] or time.time()
        start = min(since, last)
        # Spread over the year, with the newest one from the last time the game was played.
        dates = sorted(int(rng.uniform(start, last)) for _ in range(done))
        if dates:
            dates[-1] = int(last - rng.uniform(0, DAY / 4))
        invented[game["app_id"]] = [
            {
                "api_name": f"DEMO_{n}",
                "name": ACHIEVEMENT_NAMES[(n + abs(game["app_id"])) % len(ACHIEVEMENT_NAMES)],
                "description": "",
                "achieved": n < done,
                "unlocked_at": dates[n] if n < done else None,
            }
            for n in range(total)
        ]
    return invented


def _invent_rarity(rng: random.Random, app_ids: list[int]) -> list[tuple[int, dict[str, float]]]:
    """How many players have each made-up achievement: the first ones in a game are common, later ones rare.

    Players unlock the early ones first (see _invent_achievements), so someone
    deep into a game holds a properly rare one, like on real Steam.
    """
    rarity = []
    for app_id in app_ids:
        common = rng.uniform(55, 95)
        fade = rng.uniform(0.86, 0.95)
        rarity.append((app_id, {f"DEMO_{n}": max(0.1, round(common * fade**n, 1)) for n in range(60)}))
    return rarity


def _friend_library(rng: random.Random, games: list[dict]) -> list[dict]:
    """A second player who owns about two thirds of the same games, with their own hours."""
    theirs = []
    for game in games:
        if rng.random() > 0.66:
            continue
        if game["minutes"] > 600:
            minutes = round(game["minutes"] * rng.uniform(0.1, 1.9))
        else:
            minutes = _shelf_minutes(rng)
        theirs.append({**game, "minutes": minutes, "minutes_2weeks": 0, "last_played": game["last_played"] if minutes else None})
    return theirs
