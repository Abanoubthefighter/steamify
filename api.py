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


# --- The one function that actually goes online ------------------------------


def _get(interface: str, method: str, version: int = 1, key: str | None = None, **params) -> dict:
    """Call one Steam endpoint and return the "response" part of its JSON."""
    key = key or config.STEAM_API_KEY
    if not key:
        raise MissingKey()

    url = f"{config.STEAM_API_BASE}/{interface}/{method}/v{version}/"
    try:
        reply = _session.get(url, params={"key": key, **params}, timeout=config.REQUEST_TIMEOUT)
    # "from None" matters here. The original error text contains the full URL,
    # API key included, and that must not end up in a log or a traceback.
    except requests.Timeout:
        raise SteamTimeout() from None
    except requests.ConnectionError:
        raise NoConnection() from None
    except requests.RequestException:
        raise SteamError() from None

    if reply.status_code in (401, 403):
        raise BadKey()
    if reply.status_code == 429:
        raise RateLimited()
    if not reply.ok:
        raise SteamDown()
    try:
        return reply.json().get("response", {})
    except ValueError:  # the body wasn't JSON
        raise SteamDown() from None


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
    }


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
