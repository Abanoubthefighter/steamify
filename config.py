"""Every setting for the app, in one place.

Nothing else in the project hardcodes a number, a path or a URL. If you want
the app to behave differently, this should be the only Python file you need
to open. (Same idea for the looks: static/css/theme.css.)
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv, set_key

# --- The app itself ----------------------------------------------------------

APP_NAME = "Steam Stats Tracker"
APP_VERSION = "1.3.0"         # bump for a new release; the .exe and the installer read it from here
APP_ID = "SteamStatsTracker"  # no spaces: used for the data folder and to spot a copy that's already open

# --- Where things live -------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent


def _user_data_dir() -> Path:
    """Folder that holds the .env file and the database.

    Running from source, that's just the project folder. Packaged as an .exe
    there is no project folder, so we use %LOCALAPPDATA% like other Windows
    programs do.
    """
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_ID
    return APP_DIR


DATA_DIR = _user_data_dir()
ENV_FILE = DATA_DIR / ".env"
DATABASE_PATH = DATA_DIR / "data" / "steam_stats.db"
WALLPAPER_DIR = DATA_DIR / "data" / "wallpapers"  # the app's own copy of an imported picture

load_dotenv(ENV_FILE)

# --- Steam -------------------------------------------------------------------

STEAM_API_KEY = os.getenv("STEAM_API_KEY", "").strip()
DEFAULT_STEAM_ID = os.getenv("DEFAULT_STEAM_ID", "").strip()

STEAM_API_BASE = "https://api.steampowered.com"
STEAM_KEY_PAGE = "https://steamcommunity.com/dev/apikey"
STEAM_STORE_PAGE = "https://store.steampowered.com/app/{app_id}"
STEAM_ICON_URL = "https://media.steampowered.com/steamcommunity/public/images/apps/{app_id}/{icon}.jpg"
STEAM_ART_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
# The only outside hosts the page may load pictures from (avatars, icons, game art).
IMAGE_HOSTS = "https://*.steamstatic.com https://*.steampowered.com https://*.akamaihd.net"

REQUEST_TIMEOUT = 8     # seconds to wait for Steam before giving up
CACHE_MINUTES = 15      # a player scanned this recently isn't fetched again
AUTO_SYNC = True        # refresh in the background when saved data is older than that

# --- Dashboard ---------------------------------------------------------------

TOP_GAMES_COUNT = 8     # folders in C:\top_games
RECENT_GAMES_COUNT = 3  # "2w" documents shown next to them
LIBRARY_PAGE_SIZE = 50  # rows in library.exe before "show all"
SHARED_GAMES_COUNT = 5  # games listed in versus.exe
CHART_GAMES_COUNT = 8   # bars in the top games chart
PLAYERS_IN_MENU = 50    # saved players listed in the start menu, newest first (the list scrolls)

# Range buttons on the history chart: label -> (bar size, number of bars).
# None means "as far back as the log goes".
HISTORY_RANGES = {
    "30D": ("day", 30),
    "6M": ("month", 6),
    "1Y": ("month", 12),
    "ALL": ("month", None),
}
DEFAULT_HISTORY_RANGE = "6M"

# The same for the achievements chart (bar size "month" or "year"). The first one is shown first.
UNLOCK_RANGES = {
    "1Y": ("month", 12),
    "ALL": ("year", None),
}

# Edges, in hours, for the "how far did you get" chart.
# [1, 10, 50, 100] makes: never, under 1 h, 1-10 h, 10-50 h, 50-100 h, 100 h+
PLAYTIME_EDGES = [1, 10, 50, 100]

# --- Alerts (warning.exe) ----------------------------------------------------

OBSESSION_PERCENT = 30  # one game above this share of all playtime gets called out
BINGE_HOURS = 40        # this many hours in two weeks counts as a binge
ABANDONED_DAYS = 365    # a favourite untouched for this long counts as abandoned
FAVOURITES_COUNT = 10   # how far down the most-played list still counts as "a favourite"
MAX_ALERTS = 5

# --- Achievements (achievements.exe) -------------------------------------------

ACHIEVEMENT_WORKERS = 4     # games asked about at the same time during a scan (Steam has one call per game)
SLOW_DOWN_RETRIES = 3       # if Steam says "slow down" mid-scan, wait and carry on (one game at a time) this many times
SLOW_DOWN_SECONDS = 5       # the first wait; the second is twice as long, and so on
NOT_PUBLIC_GIVE_UP = 10     # a player who never shared an achievement and refuses this many games counts as private
NEARLY_DONE_PERCENT = 80    # "so close": at least this much of a game's achievements, but not all
NEARLY_DONE_COUNT = 3       # games listed under "so close"
RECENT_UNLOCKS_COUNT = 4    # latest unlocks listed
RARITY_REFRESH_DAYS = 7     # how rare each achievement is barely changes, so it's fetched at most this often

# --- Wallpaper (wallpaper.exe) -----------------------------------------------

# The built-in wallpapers: key -> name shown in wallpaper.exe. Each key has a
# .pattern--<key> rule in style.css that draws it (colours in theme.css).
# Drawings like "hills" also have their shapes in partials/wallpaper_art.html.
WALLPAPER_PATTERNS = {
    "hills": "Hills",
    "sunburst": "Sunburst",
    "dots": "Halftone dots",
    "checker": "Soft checker",
    "plain": "Plain orange",
}
DEFAULT_WALLPAPER = "hills"
WALLPAPER_MAX_MB = 25       # biggest picture that can be imported
DEFAULT_WALLPAPER_DIM = 30  # percent the dim slider starts at
WALLPAPER_DIM_MAX = 80      # percent; past this a picture is barely there

# --- Running in the tray, syncing in the background (settings.exe) --------------

KEEP_RUNNING_DEFAULT = True  # the close button hides the window to the tray, like Steam or Discord
# The one-time Windows notice the first time the window hides.
TRAY_NOTICE = "Still running down here, next to the clock. Right-click the icon to quit."

BACKGROUND_SYNC_DEFAULT = True  # sync every saved player now and then while the app is open
BACKGROUND_SYNC_MINUTES = 60    # how often each player is synced (in the window or in the tray)
BACKGROUND_CHECK_MINUTES = 5    # how often the app looks whether someone is due

# --- Badges (badges.exe) -----------------------------------------------------------

# Earned by keeping the app running (in the window or the tray), smallest first:
# (key, name, hours of running). Each key has its drawing in partials/badge_art.html
# and its colours in theme.css (--badge-*).
BADGES = [
    ("dialup", "Dial-up", 6),
    ("floppy", "Floppy", 12),
    ("cdrom", "CD-ROM", 25),
    ("dvd", "DVD", 50),
    ("harddrive", "Hard drive", 75),
    ("ram", "RAM stick", 150),
]
RUNNING_TICK_SECONDS = 60   # how often running time is added up; also the most one tick can add (so sleep doesn't count)

# --- Desktop window ----------------------------------------------------------

WINDOW_TITLE = APP_NAME
WINDOW_SIZE = (1280, 880)   # what the window opens at, if the screen is big enough
WINDOW_MIN_SIZE = (720, 560)
SCREEN_MARGIN = 80          # room always left around the window on small screens

# --- Local server ------------------------------------------------------------

HOST = "127.0.0.1"      # only this computer can connect
PORT = 0                # desktop mode: 0 lets Windows pick any free port
DEV_PORT = 5000         # browser mode (py app.py)
DEBUG = os.getenv("FLASK_DEBUG") == "1"


def save_api_key(key: str) -> None:
    """Write the key to .env and start using it straight away."""
    global STEAM_API_KEY
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.touch(exist_ok=True)
    set_key(ENV_FILE, "STEAM_API_KEY", key)
    STEAM_API_KEY = key
