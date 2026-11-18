"""tray.py: what the close button does, with a pretend window and icon."""

import pytest

import config
import preferences
import tray as tray_module
from tray import Tray


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self):
        self.calls = []
        self.events = type("Events", (), {"closing": FakeEvent()})()

    def __getattr__(self, name):  # hide(), show(), restore(), destroy() just get written down
        return lambda: self.calls.append(name)


class FakeIcon:
    def __init__(self):
        self.notices = []
        self.stopped = False

    def notify(self, message, title):
        self.notices.append(message)

    def stop(self):
        self.stopped = True


def tray_with(icon=None):
    """A tray attached to a pretend window. Pass icon=False for "pystray isn't installed"."""
    fake_icon = FakeIcon() if icon is None else (None if icon is False else icon)
    tray = Tray(make_icon=lambda tray: fake_icon)
    window = FakeWindow()
    tray.attach(window)
    return tray, window, fake_icon


def test_attach_takes_over_the_close_button():
    tray, window, _ = tray_with()
    assert window.events.closing.handlers == [tray.on_closing]


def test_closing_hides_the_window_and_says_so_the_first_time_only():
    tray, window, icon = tray_with()
    assert tray.on_closing() is False  # False cancels the close
    assert tray.on_closing() is False
    assert window.calls == ["hide", "hide"]
    assert icon.notices == [config.TRAY_NOTICE]


def test_closing_quits_when_keep_running_is_off():
    preferences.update(keep_running=False)
    tray, window, icon = tray_with()
    assert tray.on_closing() is True
    assert window.calls == [] and icon.notices == []


def test_without_a_tray_icon_closing_quits():
    tray, window, _ = tray_with(icon=False)
    assert tray.on_closing() is True
    assert window.calls == []


def test_quit_closes_for_real():
    tray, window, _ = tray_with()
    tray.quit()
    assert window.calls == ["destroy"]
    assert tray.on_closing() is True  # the close that destroy() starts isn't cancelled


def test_open_brings_the_window_back():
    tray, window, _ = tray_with()
    tray.on_closing()
    tray.show_window()
    assert window.calls == ["hide", "show", "restore"]


def test_stop_takes_the_icon_away_once():
    tray, _, icon = tray_with()
    tray.stop()
    tray.stop()
    assert icon.stopped and tray.icon is None


def test_the_menu_has_sync_now_only_when_there_is_something_to_run(monkeypatch):
    pystray = tray_module.pystray
    if pystray is None:
        pytest.skip("pystray isn't installed, so there's no menu")
    started = []

    class FakeIcon:
        def __init__(self, name, image, title, menu):
            self.labels = [item.text for item in menu.items if item is not pystray.Menu.SEPARATOR]

        def run_detached(self):
            started.append(self)

    monkeypatch.setattr(pystray, "Icon", FakeIcon)
    assert tray_module._make_icon(Tray(sync_now=lambda: None)).labels == ["Open", "Sync now", "Quit"]
    assert tray_module._make_icon(Tray()).labels == ["Open", "Quit"]
    assert len(started) == 2  # both icons were started on their own thread


def test_notify_goes_through_the_icon_if_there_is_one():
    tray, _, icon = tray_with()
    tray.notify("hello")
    assert icon.notices == ["hello"]
    no_icon, _, _ = tray_with(icon=False)
    no_icon.notify("hello")  # nothing to show it with, and no error either
