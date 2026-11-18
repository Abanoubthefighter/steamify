"""Opens the dashboard in its own window, like any other desktop program.

How it works: the Flask app from app.py runs on a background thread, at an
address only this computer can reach. Then pywebview opens a native window
(on Windows it uses Edge WebView2, which ships with Windows 10 and 11) and
points it at that address. An icon goes in the tray next to the clock
(tray.py). Closing the window hides it there, unless "Keep running in the
tray" is off in settings.exe; quitting from the icon or from Start > Shut
down ends the whole program. While it runs, background.py syncs the saved
players about once an hour.

    py desktop.py
"""

import ctypes
import os
import sys
from ctypes import wintypes


def drop_unwanted_console() -> None:
    """Close the console window if it was opened only for this program.

    run.bat starts the app with pythonw, which isn't supposed to open a
    console at all. Python 3.13.0 has a bug where it does anyway inside a
    virtual environment. If this program is the only one attached to the
    console, nobody asked for it and nobody is reading it, so it can go.
    Started from a terminal, the shell is attached as well and nothing happens.
    """
    if sys.platform != "win32":
        return
    kernel32 = ctypes.windll.kernel32
    attached = kernel32.GetConsoleProcessList((ctypes.c_uint * 2)(), 2)
    if attached == 1:
        kernel32.FreeConsole()
        # print() must not fail later just because nobody is listening.
        sys.stdout = sys.stderr = open(os.devnull, "w")


# Done before the slower imports below, so the stray window is gone almost at once.
drop_unwanted_console()

import logging  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import webbrowser  # noqa: E402

from werkzeug.serving import make_server  # noqa: E402

import config  # noqa: E402
import startup  # noqa: E402
import tray as tray_icon  # noqa: E402
from app import app, prepare  # noqa: E402
from background import BackgroundSync  # noqa: E402
from tray import Tray  # noqa: E402

try:
    import webview
except ImportError:  # the app still works without it, in a normal browser tab
    webview = None

THEME_FILE = config.APP_DIR / "static" / "css" / "theme.css"
SHOW_SIGNAL = f"{config.APP_ID}-show"  # a named event a second copy raises: "show your window"

# Windows numbers used below
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9              # ShowWindow: un-minimise
EVENT_MODIFY_STATE = 0x0002  # enough access to raise an event someone else made
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
ASFW_ANY = 0xFFFFFFFF       # AllowSetForegroundWindow: any program may come to the front


def already_running(name: str = config.APP_ID) -> bool:
    """True if another copy of the app is open already.

    A named mutex is a flag Windows keeps for as long as the program that made
    it is running. The first copy creates it. A second copy (the shortcut was
    double-clicked twice) gets "already exists" back and knows it isn't alone.
    The installer checks for the same name before it updates or removes the app.
    """
    if sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, name)  # held until this program exits
    return ctypes.get_last_error() == ERROR_ALREADY_EXISTS


def _kernel32():
    """kernel32 with the types the event functions need (handles are 64 bits wide)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return kernel32


def listen_for_second_copies(on_signal, name: str = SHOW_SIGNAL) -> None:
    """Call on_signal() every time another copy asks this one to show itself.

    The window may be hidden in the tray. Another program could find it, but
    showing it from outside would leave pywebview unsure whether its own
    window is visible. So a second copy only raises a named event (a flag
    Windows keeps by name, like the mutex), and this copy shows its own
    window when the flag goes up.
    """
    if sys.platform != "win32":
        return
    kernel32 = _kernel32()
    signal = kernel32.CreateEventW(None, False, False, name)  # resets itself: one wake-up per raise

    def wait() -> None:
        while kernel32.WaitForSingleObject(signal, INFINITE) == WAIT_OBJECT_0:
            on_signal()

    threading.Thread(target=wait, daemon=True, name="second-copies").start()


def ask_open_copy_to_show(name: str = SHOW_SIGNAL) -> bool:
    """Ask the copy that's already open to show its window. False if it isn't listening."""
    kernel32 = _kernel32()
    signal = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not signal:
        return False
    # Windows only lets the program the user just clicked take the front. That
    # was this one, so pass the right on to the copy that's already open.
    ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    kernel32.SetEvent(signal)
    kernel32.CloseHandle(signal)
    return True


def show_open_copy() -> None:
    """Bring the window of the copy that's already open to the front, even out of the tray."""
    if ask_open_copy_to_show():
        return
    # A copy from before 1.3.0 doesn't listen for that yet: find its window instead.
    user32 = ctypes.windll.user32
    window = user32.FindWindowW(None, config.WINDOW_TITLE)
    if not window:
        return
    if user32.IsIconic(window):  # minimised to the taskbar
        user32.ShowWindow(window, SW_RESTORE)
    user32.SetForegroundWindow(window)


def start_server() -> str:
    """Run Flask in the background and return the address it ended up on."""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # don't log every request
    # threaded=True gives each request its own thread, so a scan that is
    # still streaming its progress doesn't hold up the rest of the page.
    server = make_server(config.HOST, config.PORT, app, threaded=True)
    # A daemon thread is stopped automatically when the main program exits.
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://{config.HOST}:{server.server_port}"


def theme_color(name: str, fallback: str) -> str:
    """Read one colour out of theme.css.

    The window gets painted before the page has loaded. Giving it the page's
    own background colour avoids a white flash, and reading that colour from
    the CSS means theme.css stays the only place a colour is written down.
    """
    try:
        match = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})\b", THEME_FILE.read_text(encoding="utf-8"))
    except OSError:
        return fallback
    return match.group(1) if match else fallback


class Bridge:
    """The few things the page may ask the desktop shell to do.

    pywebview hands this object to the page's JavaScript as
    window.pywebview.api. "Shut down" in the start menu calls quit(), which
    quits for real even when closing the window would only hide it.
    """

    def __init__(self, tray: Tray):
        self._tray = tray  # the underscore keeps pywebview from offering it to the page as well

    def quit(self) -> None:
        self._tray.quit()


def window_size() -> tuple[int, int]:
    """The size from config.py, shrunk if this screen is too small for it."""
    width, height = config.WINDOW_SIZE
    screen = webview.screens[0]
    return (
        min(width, screen.width - config.SCREEN_MARGIN),
        min(height, screen.height - config.SCREEN_MARGIN),
    )


def starts_hidden(arguments: list[str]) -> bool:
    """True when Windows started the app at login (startup.py adds --tray): open straight into the tray.

    Only if there's a tray icon to open it from, or the window would be lost.
    """
    return startup.TRAY_FLAG in arguments[1:] and tray_icon.available()


def create_window(url: str, bridge: Bridge, hidden: bool = False):
    """A native window pointed at the local server. `hidden` starts it in the tray."""
    width, height = window_size()
    return webview.create_window(
        config.WINDOW_TITLE,
        url,
        js_api=bridge,
        hidden=hidden,
        width=width,
        height=height,
        min_size=config.WINDOW_MIN_SIZE,
        background_color=theme_color("bg", "#f7a04b"),
        text_select=True,  # so names and numbers can be copied
    )


def main() -> None:
    if already_running():
        show_open_copy()
        return

    prepare()
    url = start_server()

    if webview is None:
        print("pywebview isn't installed, so the app is opening in your browser instead.")
        print(f"It's running at {url}. Press Ctrl+C here to stop it.")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return

    app.config["DESKTOP_APP"] = True  # read per request, so settings.exe can offer the tray from now on
    syncing = BackgroundSync()
    syncing.start()  # every saved player, about once an hour, while the app is open
    tray = Tray(sync_now=syncing.sync_now)
    tray.attach(create_window(url, Bridge(tray), hidden=starts_hidden(sys.argv)))
    listen_for_second_copies(tray.show_window)  # a second double-click brings this window back
    try:
        webview.start(debug=config.DEBUG)  # blocks until the window is really closed, not just hidden
    finally:
        tray.stop()  # the icon has its own thread, which would keep the program alive


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Started by run.bat (or as the packaged .exe) there is no console to
        # print an error to, so the app would just fail to appear. Leave a
        # note on disk instead.
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / "crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
