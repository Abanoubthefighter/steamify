"""Start with Windows: one value in the user's "Run" list in the registry.

Windows starts every program listed under
HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run when that user
logs in. Turning the setting on adds the app there, with --tray so it
starts hidden next to the clock (desktop.py) and syncs in the background.
Turning it off removes the value again, and so does the uninstaller.

The registry itself is the setting: nothing is saved in the database, so the
box in settings.exe always shows what Windows will really do. Only the
installed app (a real .exe) offers it. Run from source there's no single
program Windows could start.
"""

import sys

import config

try:
    import winreg
except ImportError:  # not Windows
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Where Task Manager's Startup tab (and Settings > Apps > Startup) remembers
# programs that were switched off there. The Run value stays, but Windows skips it.
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE_NAME = config.APP_ID  # the installer's uninstall step removes this same name
TRAY_FLAG = "--tray"        # desktop.py starts hidden in the tray when it sees this


class StartupError(Exception):
    """The setting couldn't be changed, with a title and message for a popup."""

    title = "Can't change that"


def available() -> bool:
    """True if this copy can be started by Windows: the packaged .exe, on Windows."""
    return winreg is not None and bool(getattr(sys, "frozen", False))


def command() -> str:
    """What Windows runs at login: this .exe, quoted (the path has spaces), plus --tray."""
    return f'"{sys.executable}" {TRAY_FLAG}'


def is_on() -> bool:
    """True if Windows will start this copy at login."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:  # no Run key, or no value for us in it
        return False
    # A value left by a copy installed somewhere else doesn't count: it wouldn't start this one.
    return value == command() and not _switched_off_in_windows()


def _switched_off_in_windows() -> bool:
    """True if the app was switched off in Task Manager's Startup tab."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            data, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    # The first byte is even (2) for "on" and odd (3) for "switched off".
    return bool(data) and data[0] % 2 == 1


def turn_on() -> None:
    if not available():
        raise StartupError("Only the installed app can start with Windows.")
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
    except OSError as error:
        raise StartupError("Windows wouldn't let the app add itself to the programs it starts.") from error
    # If it was switched off in Task Manager before, forget that, or Windows would still skip it.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except OSError:
        pass  # never switched off there


def turn_off() -> None:
    if winreg is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass  # already off
    except OSError as error:
        raise StartupError("Windows wouldn't let the app take itself off the programs it starts.") from error
