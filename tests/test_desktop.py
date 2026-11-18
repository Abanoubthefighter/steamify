"""desktop.py: the parts that work without opening a real window."""

import re
import sys
import threading
import uuid

import pytest

import desktop


@pytest.mark.skipif(sys.platform != "win32", reason="the single-copy check uses a Windows mutex")
def test_a_second_copy_notices_the_first():
    # A made-up name, so an app that happens to be open doesn't affect the test.
    name = f"SteamStatsTracker-test-{uuid.uuid4().hex}"
    assert desktop.already_running(name) is False
    assert desktop.already_running(name) is True


def test_window_background_comes_from_theme_css():
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", desktop.theme_color("bg", "fallback"))
    assert desktop.theme_color("no-such-colour", "fallback") == "fallback"


@pytest.mark.skipif(sys.platform != "win32", reason="the show signal is a Windows named event")
def test_a_second_copy_can_ask_the_first_to_show_itself():
    name = f"SteamStatsTracker-test-{uuid.uuid4().hex}"
    assert desktop.ask_open_copy_to_show(name) is False  # nobody listening yet
    asked = threading.Event()
    desktop.listen_for_second_copies(asked.set, name)
    assert desktop.ask_open_copy_to_show(name) is True
    assert asked.wait(timeout=5)
