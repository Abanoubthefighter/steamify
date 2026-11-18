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
- **wallpaper.exe**: swap the desktop pattern, or import your own picture and dim it so the windows stay readable. It's under Start > Change wallpaper.
- **A working desktop**: drag windows, minimise them to the taskbar, maximise the chart, bring things back from the start menu.

[Full-page screenshot](docs/dashboard-full.png)

## Installing

Run `SteamStatsTracker-1.1.0-Setup.exe` (see [Building the installer](#building-the-installer) to make it). It installs just for you, so no admin password, and adds the app to the Start menu. You can also tick a desktop icon.

- Windows may show "Windows protected your PC" because the installer isn't code-signed. Click **More info**, then **Run anyway**.
- To update, run the newer installer. Your play history and API key stay.
- To remove it, use **Settings > Apps > Installed apps**. It asks whether to delete your saved data too.

## Running it from source

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

### Building the installer

You need [Inno Setup 6](https://jrsoftware.org/isinfo.php) (free) on top of the usual setup. Then double-click `build_exe.bat`. It takes under a minute and makes two things in `dist\`:

- `SteamStatsTracker\`: the app, built by PyInstaller from `packaging\SteamStatsTracker.spec`. It runs without Python.
- `SteamStatsTracker-<version>-Setup.exe` (for example `SteamStatsTracker-1.1.0-Setup.exe`): that folder packed into an installer by Inno Setup, from `packaging\installer.iss`. This is the file to share.

Without Inno Setup you still get the folder. A few things worth knowing:

- **The .exe needs its `_internal` folder.** That's where Python itself lives. Copy `SteamStatsTracker.exe` somewhere on its own and it stops with "Failed to load Python DLL". The installer exists so nobody has to know that.
- **Why a folder and not one big .exe.** A single-file build unpacks itself into a temp folder on every start. Measured here, it opened in 1.1 s against 0.7 s for the folder, and it leaves those temp folders behind if it's ever killed.
- **The version number** lives in `config.py` as `APP_VERSION`. The .exe's Properties tab, the About box and the installer's file name all read it from there.
- The installed app keeps its database, its `.env` and your wallpaper picture in `%LOCALAPPDATA%\SteamStatsTracker`, not next to the program, which is why updates don't touch them.

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
wallpaper.py   the wallpaper choice and the imported picture
config.py      every setting in one place
run.bat        sets things up on the first run, then opens the app
build_exe.bat  builds the app and its installer
packaging/     the PyInstaller and Inno Setup recipes build_exe.bat uses
templates/     one file per window, built from a shared window macro
static/css/    theme.css (all colours, fonts, sizes) and style.css (layout)
static/js/     window manager, scan progress, library, charts
tests/         162 tests, none of which go online
```

A few decisions worth explaining:

- **History without a history API.** Each scan compares the new totals with the saved ones and writes only the differences to a `play_log` table. A normal day adds a handful of rows instead of one per game owned. In a test with 3,000 games and 400 days of play the log held about 2,100 rows and the database was 360 KB.
- **Saved data first, Steam second.** The dashboard is drawn from SQLite, so it opens straight away and works offline. If the data is older than 15 minutes the page asks for a fresh scan in the background.
- **One connection to Steam.** A shared `requests.Session` keeps the connection open between calls. Measured here, the first call took about 600 ms and the following ones about 250 ms.
- **Sorting lives in Python only.** The page asks the server for re-sorted rows as HTML instead of repeating the sort rules in JavaScript.
- **An imported wallpaper is a copy.** The app checks the file's first bytes (not its name) to make sure it's really a PNG, JPG or WebP, then copies it into its data folder, so moving or deleting the original changes nothing. The copy is named after a fingerprint of its contents, which means a new picture never shows up as the old one from the cache.
- **Names from Steam are untrusted.** Templates escape everything, a Content-Security-Policy blocks inline scripts, and the local server refuses requests that didn't come from its own window.
- **Errors are written for people.** Bad key, private profile, timeout, no connection: each one is its own exception with a title and message that go straight into a popup. The API key is kept out of error text on purpose.
- **One copy at a time.** On start the app claims a named Windows mutex. If a copy already holds it, the new one brings that window forward and quits, so a double double-click doesn't give you two windows writing to the same database. The installer checks the same name and asks you to close the app before it updates or removes it.

On my machine the dashboard for a 3,000-game library renders in about 25 ms, and saving a scan of that size takes about 14 ms.

## Making it yours

- **Colours, fonts, outline thickness, spacing:** `static/css/theme.css`. Nothing else contains a colour, and the charts read theirs from the same file.
- **Behaviour:** `config.py` (how many top games, cache time, chart ranges, alert thresholds, window size, version number).
- **The jokes:** `captions.py`.
- **A new wallpaper pattern:** add a name to `WALLPAPER_PATTERNS` in `config.py` and a `.pattern--<name>` rule in `style.css`. It shows up in wallpaper.exe, preview included.
- **A new sort order:** add one function and one line to `SORT_ORDERS` in `stats.py`. The radio button appears on its own.
- **Window order:** reorder the `include` lines in `templates/dashboard.html`.

## Tests

```bash
py -m pip install -r requirements-dev.txt
py -m pytest
```

## Known limits

- History only starts when you first scan, and playtime is dated to the day of the scan that noticed it. Scan often and the chart gets finer.
- Windows only for now. pywebview supports macOS and Linux, but the `.bat` files, the installer and the console and single-copy code in `desktop.py` are Windows things.
- The installer and the .exe aren't code-signed (a certificate costs money every year), so Windows SmartScreen warns about them on other PCs.

## Credits

- Fonts: [Fredoka](https://fonts.google.com/specimen/Fredoka) and [Josefin Sans](https://fonts.google.com/specimen/Josefin+Sans), both under the SIL Open Font License (copies in `static/fonts`).
- Charts: [Chart.js](https://www.chartjs.org/) 4.6.1, MIT licence.
- Data: the [Steam Web API](https://developer.valvesoftware.com/wiki/Steam_Web_API). This project isn't affiliated with Valve.
