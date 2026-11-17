"""Opens the dashboard in its own window, like any other desktop program.

How it works: the Flask app from app.py runs on a background thread, at an
address only this computer can reach. Then pywebview opens a native window
(on Windows it uses Edge WebView2, which ships with Windows 10 and 11) and
points it at that address. Close the window and the whole program ends.

    py desktop.py
"""

import ctypes
import os
import sys


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
from app import app, prepare  # noqa: E402

try:
    import webview
except ImportError:  # the app still works without it, in a normal browser tab
    webview = None

THEME_FILE = config.APP_DIR / "static" / "css" / "theme.css"
ERROR_ALREADY_EXISTS = 183  # Windows error code
SW_RESTORE = 9              # ShowWindow: un-minimise


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


def show_open_copy() -> None:
    """Bring the window of the copy that's already open to the front."""
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
    window.pywebview.api. "Shut down" in the start menu calls quit().
    """

    def quit(self) -> None:
        for window in webview.windows:
            window.destroy()


def window_size() -> tuple[int, int]:
    """The size from config.py, shrunk if this screen is too small for it."""
    width, height = config.WINDOW_SIZE
    screen = webview.screens[0]
    return (
        min(width, screen.width - config.SCREEN_MARGIN),
        min(height, screen.height - config.SCREEN_MARGIN),
    )


def create_window(url: str):
    """A native window pointed at the local server."""
    width, height = window_size()
    return webview.create_window(
        config.WINDOW_TITLE,
        url,
        js_api=Bridge(),
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

    create_window(url)
    webview.start(debug=config.DEBUG)  # blocks until the window is closed


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
