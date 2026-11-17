# Steam Stats Tracker

A small desktop app that reads a Steam library, remembers how it changes, and shows it all on a pretend retro desktop: every stat lives in its own little window you can drag around, minimise and close.

![The dashboard with the demo player](docs/dashboard.png)

It opens in its own window (not a browser tab), works without an API key thanks to a built-in demo player, and keeps everything it learns in a local SQLite file.

## What it does

- **Scan a profile** by Steam ID, profile link or custom URL name. The progress bar is real: the server reports each step as it finishes.
- **Playtime history.** Steam only ever tells you lifetime totals, so the app logs the difference between scans and builds its own history from that.
- **Top games, recent games and the full library**, sortable and searchable.
- **warning.exe**: a stack of popups about your habits (how much of your library you never opened, that one game eating a third of your time).
- **versus.exe**: compare with a friend, game by game.
- **A working desktop**: drag windows, minimise them to the taskbar, maximise the chart, bring things back from the start menu.

[Full-page screenshot](docs/dashboard-full.png)

## Running it

You need Windows 10 or 11 and Python 3.10 or newer.

**The easy way:** double-click `run.bat`. The first run sets up a virtual environment and installs the dependencies, later runs just open the app.

**By hand:**

```bash
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
py desktop.py
```

`py app.py` runs the same thing in a normal browser at http://127.0.0.1:5000, which is handy while changing the CSS.

### As a standalone .exe

Double-click `build_exe.bat`. It uses PyInstaller to build `dist\SteamStatsTracker`, a folder with a `SteamStatsTracker.exe` inside that runs on a PC without Python. Zip the folder to share it.

- It's a folder rather than one big .exe on purpose. A single-file build has to unpack itself into a temp folder on every start, which makes it slow to open. This way the window is up in about a second.
- The very first launch after building takes a few seconds longer while Windows checks the new files.
- The .exe isn't code-signed, so Windows may ask for confirmation before running it on another PC.
- The packaged app keeps its database and `.env` in `%LOCALAPPDATA%\SteamStatsTracker` instead of the project folder.

## Using your own Steam data

The app starts with a made-up player so there's something to look at. To see a real library you need a free Steam Web API key:

1. Get one at https://steamcommunity.com/dev/apikey (any domain name works, `localhost` is fine).
2. Paste it into **scan.exe** inside the app. It checks the key with Steam and saves it to `.env`.

Or copy `.env.example` to `.env` and put the key there yourself. `.env` is in `.gitignore`, so the key never ends up on GitHub.

The profile you scan needs its **Game details** set to Public in Steam's privacy settings.

## How it's put together

```
desktop.py     opens the native window (pywebview) and runs Flask behind it
app.py         routes only
api.py         everything that talks to Steam, plus friendly error messages
sync.py        one scan: resolve the ID, fetch, save
storage.py     SQLite: players, libraries and the play log
stats.py       totals, sorting, searching (pure functions)
charts.py      decides what each chart shows
captions.py    the jokes in the warning popups
demo.py        the made-up player
config.py      every setting in one place
run.bat        sets things up on the first run, then opens the app
build_exe.bat  builds the standalone .exe
templates/     one file per window, built from a shared window macro
static/css/    theme.css (all colours, fonts, sizes) and style.css (layout)
static/js/     window manager, scan progress, library, charts
tests/         123 tests, none of which go online
```

A few decisions worth explaining:

- **History without a history API.** Each scan compares the new totals with the saved ones and writes only the differences to a `play_log` table. A normal day adds a handful of rows instead of one per game owned. In a test with 3,000 games and 400 days of play the log held about 2,100 rows and the database was 360 KB.
- **Saved data first, Steam second.** The dashboard is drawn from SQLite, so it opens straight away and works offline. If the data is older than 15 minutes the page asks for a fresh scan in the background.
- **One connection to Steam.** A shared `requests.Session` keeps the connection open between calls. Measured here, the first call took about 600 ms and the following ones about 250 ms.
- **Sorting lives in Python only.** The page asks the server for re-sorted rows as HTML instead of repeating the sort rules in JavaScript.
- **Names from Steam are untrusted.** Templates escape everything, a Content-Security-Policy blocks inline scripts, and the local server refuses requests that didn't come from its own window.
- **Errors are written for people.** Bad key, private profile, timeout, no connection: each one is its own exception with a title and message that go straight into a popup. The API key is kept out of error text on purpose.

On my machine the dashboard for a 3,000-game library renders in about 25 ms, and saving a scan of that size takes about 14 ms.

## Making it yours

- **Colours, fonts, outline thickness, spacing:** `static/css/theme.css`. Nothing else contains a colour, and the charts read theirs from the same file.
- **Behaviour:** `config.py` (how many top games, cache time, chart ranges, alert thresholds, window size).
- **The jokes:** `captions.py`.
- **A new sort order:** add one function and one line to `SORT_ORDERS` in `stats.py`. The radio button appears on its own.
- **Window order:** reorder the `include` lines in `templates/dashboard.html`.

## Tests

```bash
py -m pip install -r requirements-dev.txt
py -m pytest
```

## Known limits

- History only starts when you first scan, and playtime is dated to the day of the scan that noticed it. Scan often and the chart gets finer.
- Windows only for now. pywebview supports macOS and Linux, but the two `.bat` files and the console workaround in `desktop.py` are Windows things.

## Credits

- Fonts: [Fredoka](https://fonts.google.com/specimen/Fredoka) and [Josefin Sans](https://fonts.google.com/specimen/Josefin+Sans), both under the SIL Open Font License (copies in `static/fonts`).
- Charts: [Chart.js](https://www.chartjs.org/) 4.6.1, MIT licence.
- Data: the [Steam Web API](https://developer.valvesoftware.com/wiki/Steam_Web_API). This project isn't affiliated with Valve.
