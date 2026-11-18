"""Everything that talks to Steam lives in this file.

The rest of the app never builds a URL or checks a status code. It calls a
function here and gets back either tidy data or a SteamError whose message
is already written for a human, ready to go in a popup.

Steam Web API docs: https://developer.valvesoftware.com/wiki/Steam_Web_API
"""

import re
from functools import lru_cache

import requests

import config

# One Session for the whole app. It keeps the connection to Steam open between
# calls, so only the first request of a scan pays for the HTTPS handshake.
_session = requests.Session()

STEAM_ID = re.compile(r"7656\d{13}")
PROFILE_LINK = re.compile(r"steamcommunity\.com/(?:profiles|id)/([^/?#\s]+)", re.IGNORECASE)
CUSTOM_NAME = re.compile(r"[A-Za-z0-9_-]{1,32}")
API_KEY = re.compile(r"[0-9A-Fa-f]{32}")

# What the numbers in Steam's "personastate" field mean.
STATUSES = ("Offline", "Online", "Busy", "Away", "Snooze", "Looking to trade", "Looking to play")
PUBLIC = 3  # the "communityvisibilitystate" of a profile anyone can see


# --- Errors ------------------------------------------------------------------


class SteamError(Exception):
    """Something went wrong while talking to Steam.

    Every subclass carries a `title` and a `message` written for the person
    using the app, so the UI can show them as they are. `code` is for the
    page's JavaScript, in case it wants to react to one specific problem.
    """

    code = "steam-error"
    title = "Steam hiccup"
    message = "Something went wrong talking to Steam. Try again in a minute."

    def __init__(self, message: str | None = None):
        if message:
            self.message = message
        super().__init__(self.message)

    def as_dict(self) -> dict:
        return {"code": self.code, "title": self.title, "message": self.message}


class MissingKey(SteamError):
    code = "missing-key"
    title = "No API key yet"
    message = "I can't ask Steam about real profiles without a key. Paste one into scan.exe. It's free and takes a minute."


class BadKey(SteamError):
    code = "bad-key"
    title = "Steam rejected the key"
    message = "That API key didn't work. Check it for typos, or make a new one."


class EmptyQuery(SteamError):
    code = "empty"
    title = "Nothing to scan"
    message = "Type a Steam ID, a profile link or a custom URL name first."


class ProfileNotFound(SteamError):
    code = "not-found"
    title = "Nobody by that name"

    def __init__(self, query: str):
        super().__init__(f"Steam has no profile for “{query}”. Try the 17-digit ID or the link to the profile page.")


class PrivateProfile(SteamError):
    code = "private"
    title = "This library is private"
    message = (
        "Steam won't share the game list. In Steam, open Edit Profile, then Privacy "
        "Settings, and set Game details to Public. Then scan again."
    )


class PrivateAchievements(SteamError):
    code = "private-achievements"
    title = "Achievements are private"
    message = (
        "Steam won't share the achievements. In Steam, open Edit Profile, then Privacy "
        "Settings, and set Game details to Public. Then scan again."
    )


class SteamTimeout(SteamError):
    code = "timeout"
    title = "Steam took too long"
    message = "Steam didn't answer in time. It's probably just busy, so try again in a bit."


class NoConnection(SteamError):
    code = "offline"
    title = "Can't reach Steam"
    message = "Looks like you're offline, or Steam is. Check your connection and try again."


class RateLimited(SteamError):
    code = "rate-limited"
    title = "Too many requests"
    message = "Steam asked us to slow down. Give it a few minutes."


class SteamDown(SteamError):
    code = "steam-down"
    title = "Steam is having a moment"
    message = "Steam answered with an error instead of data. That's on their side. Try again later."


# --- The functions that actually go online -----------------------------------


def _send(interface: str, method: str, version: int = 1, key: str | None = None, **params) -> requests.Response:
    """Send one request to Steam and hand back its reply, whatever the status."""
    key = key or config.STEAM_API_KEY
    if not key:
        raise MissingKey()

    url = f"{config.STEAM_API_BASE}/{interface}/{method}/v{version}/"
    try:
        return _session.get(url, params={"key": key, **params}, timeout=config.REQUEST_TIMEOUT)
    # "from None" matters here. The original error text contains the full URL,
    # API key included, and that must not end up in a log or a traceback.
    except requests.Timeout:
        raise SteamTimeout() from None
    except requests.ConnectionError:
        raise NoConnection() from None
    except requests.RequestException:
        raise SteamError() from None


def _check(reply: requests.Response) -> dict:
    """The JSON of a reply that went well. Anything else becomes a SteamError."""
    if reply.status_code in (401, 403):
        raise BadKey()
    if reply.status_code == 429:
        raise RateLimited()
    if not reply.ok:
        raise SteamDown()
    try:
        return reply.json()
    except ValueError:  # the body wasn't JSON
        raise SteamDown() from None


def _get(interface: str, method: str, version: int = 1, key: str | None = None, **params) -> dict:
    """Call one Steam endpoint and return the "response" part of its JSON."""
    return _check(_send(interface, method, version, key, **params)).get("response", {})


# --- Finding a player --------------------------------------------------------


def resolve_steam_id(text: str) -> str:
    """Turn whatever was typed into a 17-digit Steam ID.

    All of these work:
        76561197960287930
        https://steamcommunity.com/profiles/76561197960287930
        https://steamcommunity.com/id/gabelogannewell
        gabelogannewell
    """
    text = text.strip()
    link = PROFILE_LINK.search(text)
    name = link.group(1) if link else text.strip("/")
    if not name:
        raise EmptyQuery()
    if STEAM_ID.fullmatch(name):
        return name  # already an ID, nothing to look up
    if not CUSTOM_NAME.fullmatch(name):
        raise ProfileNotFound(name)  # not a shape Steam allows, so don't bother asking
    return _resolve_custom_name(name.lower())


@lru_cache(maxsize=256)
def _resolve_custom_name(name: str) -> str:
    """Ask Steam which ID a custom URL name belongs to.

    lru_cache remembers the answers, so a name is only looked up once per run.
    (Failed lookups raise, and exceptions are never cached.)
    """
    answer = _get("ISteamUser", "ResolveVanityURL", vanityurl=name)
    if answer.get("success") != 1:
        raise ProfileNotFound(name)
    return answer["steamid"]


# --- Reading a player --------------------------------------------------------


def get_player(steam_id: str) -> dict:
    """The profile card: name, avatar, online status and so on."""
    players = _get("ISteamUser", "GetPlayerSummaries", version=2, steamids=steam_id).get("players", [])
    if not players:
        raise ProfileNotFound(steam_id)
    raw = players[0]
    state = raw.get("personastate", 0)
    return {
        "steam_id": raw["steamid"],
        "name": raw.get("personaname") or "Unknown",
        "avatar": raw.get("avatarfull") or raw.get("avatarmedium"),
        "profile_url": raw.get("profileurl"),
        "status": STATUSES[state] if 0 <= state < len(STATUSES) else STATUSES[0],
        "created": raw.get("timecreated"),  # Steam leaves this out for private profiles
        "is_public": raw.get("communityvisibilitystate") == PUBLIC,
        "level": None,  # filled in separately, see get_level
    }


def get_level(steam_id: str) -> int | None:
    """Steam level, or None if Steam won't say. It's a nice-to-have, so this never raises."""
    try:
        return _get("IPlayerService", "GetSteamLevel", steamid=steam_id).get("player_level")
    except SteamError:
        return None


def get_owned_games(steam_id: str) -> list[dict]:
    """Every game in the library, in the app's own tidy shape (see _tidy_game)."""
    answer = _get(
        "IPlayerService",
        "GetOwnedGames",
        steamid=steam_id,
        include_appinfo=1,  # without this Steam sends IDs only, no names
        include_played_free_games=1,
    )
    if "games" not in answer:
        if answer.get("game_count") == 0:
            return []
        # A private library comes back as an empty answer rather than an error.
        raise PrivateProfile()
    return [_tidy_game(raw) for raw in answer["games"]]


def _tidy_game(raw: dict) -> dict:
    """Rename Steam's fields to ours and fill in the ones it sometimes leaves out."""
    return {
        "app_id": raw["appid"],
        "name": raw.get("name") or f"App {raw['appid']}",
        "icon": raw.get("img_icon_url") or None,
        "minutes": raw.get("playtime_forever", 0),
        "minutes_2weeks": raw.get("playtime_2weeks", 0),
        "last_played": raw.get("rtime_last_played") or None,
        # Steam only sends this when it's true. Games without it have no
        # achievements, so the achievement scan doesn't ask about them.
        "has_stats": bool(raw.get("has_community_visible_stats")),
    }


# --- Achievements ------------------------------------------------------------
# Steam has no "all my achievements" call, only one per game. sync.py decides
# which games are worth asking about; these functions just ask.


def get_achievements(steam_id: str, app_id: int) -> list[dict]:
    """Every achievement in one game for one player, unlocked or not.

    An empty list means the game has no achievements. Steam answers that
    with an error status, and a private profile too, so the error text in
    the reply is read before the status code gets a say.
    """
    reply = _send("ISteamUserStats", "GetPlayerAchievements", steamid=steam_id, appid=app_id, l="english")
    problem = _stats_error(reply)
    if "no stats" in problem:
        return []
    if "not public" in problem:
        raise PrivateAchievements()
    stats = _check(reply).get("playerstats", {})
    return [_tidy_achievement(raw) for raw in stats.get("achievements", []) if "apiname" in raw]


def _stats_error(reply: requests.Response) -> str:
    """The error text Steam puts inside a "playerstats" reply, in lower case, or ""."""
    try:
        return str(reply.json().get("playerstats", {}).get("error", "")).lower()
    except (ValueError, AttributeError):  # not JSON, or not the shape we expected
        return ""


def _tidy_achievement(raw: dict) -> dict:
    return {
        "api_name": raw["apiname"],
        "name": raw.get("name") or raw["apiname"],
        "description": raw.get("description") or "",
        "achieved": bool(raw.get("achieved")),
        # Some very old unlocks have no date (Steam sends 0), so this can be None even when achieved.
        "unlocked_at": raw.get("unlocktime") or None,
    }


def get_achievement_icons(app_id: int) -> dict[str, str]:
    """The icon of every achievement in a game: {api name: picture address}."""
    game = _check(_send("ISteamUserStats", "GetSchemaForGame", version=2, appid=app_id)).get("game", {})
    listed = game.get("availableGameStats", {}).get("achievements", [])
    return {item["name"]: item["icon"] for item in listed if item.get("name") and item.get("icon")}


def get_global_percentages(app_id: int) -> dict[str, float]:
    """What share of all players (in %) has each achievement in a game: {api name: percent}."""
    answer = _check(_send("ISteamUserStats", "GetGlobalAchievementPercentagesForApp", version=2, gameid=app_id))
    found = {}
    for item in answer.get("achievementpercentages", {}).get("achievements", []):
        try:
            found[item["name"]] = float(item["percent"])  # Steam has sent this both as a number and as text
        except (KeyError, TypeError, ValueError):
            continue
    return found


# --- Checking a key before we save it ----------------------------------------


def looks_like_key(text: str) -> bool:
    """Steam keys are always 32 hex characters."""
    return bool(API_KEY.fullmatch(text))


def key_works(key: str) -> bool:
    """Try a key on a harmless request. False means Steam turned it down."""
    try:
        _get("ISteamUser", "GetPlayerSummaries", version=2, key=key, steamids="76561197960265728")
    except BadKey:
        return False
    return True
