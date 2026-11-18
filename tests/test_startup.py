"""startup.py: Start with Windows, against the pretend registry from conftest."""

import sys

import pytest

import startup

EXE = r"C:\Users\someone\AppData\Local\Programs\Steam Stats Tracker\SteamStatsTracker.exe"


@pytest.fixture
def installed(monkeypatch):
    """Pretend to be the packaged .exe at EXE."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", EXE)


def run_list():
    """What's in the pretend Run key."""
    return startup.winreg.keys.get((startup.winreg.HKEY_CURRENT_USER, startup.RUN_KEY), {})


def test_from_source_it_isnt_offered():
    assert startup.available() is False
    with pytest.raises(startup.StartupError):
        startup.turn_on()
    assert run_list() == {}


def test_turning_it_on_and_off(installed):
    assert startup.available() and not startup.is_on()
    startup.turn_on()
    assert run_list() == {"SteamStatsTracker": f'"{EXE}" --tray'}  # quoted: the path has spaces
    assert startup.is_on()
    startup.turn_off()
    assert run_list() == {} and not startup.is_on()
    startup.turn_off()  # already off: nothing happens


def test_a_value_for_a_copy_somewhere_else_doesnt_count(installed):
    startup.turn_on()
    run_list()["SteamStatsTracker"] = r'"D:\old place\SteamStatsTracker.exe" --tray'
    assert not startup.is_on()
    startup.turn_on()  # pointing it at this copy again
    assert startup.is_on()


def test_other_programs_in_the_run_list_are_left_alone(installed):
    startup.turn_on()
    run_list()["SomethingElse"] = "else.exe"
    startup.turn_off()
    assert run_list() == {"SomethingElse": "else.exe"}
