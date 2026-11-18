"""The icon next to the clock, and what the window's close button does while it's there.

With "Keep running in the tray" on (settings.exe), closing the window only
hides it, the way Steam and Discord do: the app goes on running with an icon
in the notification area. Clicking the icon brings the window back, and its
right-click menu can sync everyone straight away (background.py) or quit
for real. Start > Shut down quits for real too.

pystray draws the icon and runs its own little thread for it. If pystray
isn't installed (an older .venv, say), there's simply no icon and the close
button quits like it always did.
"""

import config
import preferences

try:
    import pystray
    from PIL import Image
except ImportError:
    pystray = None

ICON_FILE = config.APP_DIR / "static" / "img" / "icon.ico"


class Tray:
    """Ties the tray icon to the pywebview window.

    Made before the window exists (the window's JavaScript bridge needs it
    for Shut down), then attach() hands it the window.
    """

    def __init__(self, sync_now=None, make_icon=None):
        self.window = None
        self.icon = None
        self.quitting = False  # set once a real quit has started, so closing stops being cancelled
        self.sync_now = sync_now  # what "Sync now" in the menu runs; no such item without it
        self._make_icon = make_icon or _make_icon

    def attach(self, window) -> None:
        """Take over the window's close button and put the icon in the tray."""
        self.window = window
        window.events.closing += self.on_closing
        self.icon = self._make_icon(self)

    def on_closing(self) -> bool:
        """pywebview calls this just before the window closes. Returning False cancels the close."""
        if self.quitting or self.icon is None or not preferences.keep_running():
            self.quitting = True
            return True
        self.window.hide()
        if preferences.first_time_hidden():
            self.icon.notify(config.TRAY_NOTICE, config.APP_NAME)
        return False

    def show_window(self) -> None:
        """Bring the window back from the tray (or from the taskbar, if it was minimised)."""
        if self.window is not None and not self.quitting:
            self.window.show()
            self.window.restore()

    def quit(self) -> None:
        """Close the window for real. desktop.py stops the icon once the window is gone."""
        self.quitting = True
        if self.window is not None:
            self.window.destroy()

    def stop(self) -> None:
        """Take the icon out of the tray. Called on the way out."""
        if self.icon is not None:
            self.icon.stop()
            self.icon = None


def _make_icon(tray: Tray):
    """The real icon, already running on its own thread. None without pystray."""
    if pystray is None:
        return None
    items = [
        # default=True: a plain click on the icon does the same as "Open".
        pystray.MenuItem("Open", tray.show_window, default=True),
        pystray.MenuItem("Sync now", tray.sync_now) if tray.sync_now else None,
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", tray.quit),
    ]
    menu = pystray.Menu(*(item for item in items if item is not None))
    icon = pystray.Icon(config.APP_ID, Image.open(ICON_FILE), config.APP_NAME, menu)
    icon.run_detached()
    return icon
