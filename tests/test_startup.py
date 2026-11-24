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


def test_switched_off_in_task_manager_counts_as_off_until_turned_on_here(installed):
    startup.turn_on()
    registry = startup.winreg
    with registry.CreateKey(registry.HKEY_CURRENT_USER, startup.APPROVED_KEY) as key:
        registry.SetValueEx(key, "SteamStatsTracker", 0, 3, bytes([3]) + bytes(11))  # what Task Manager writes
    assert not startup.is_on()
    startup.turn_on()
    assert startup.is_on()
    assert registry.keys[(registry.HKEY_CURRENT_USER, startup.APPROVED_KEY)] == {}


NEW_EXE = r"C:\Users\someone\AppData\Local\Programs\Steam Stats Tracker\Steamify.exe"


@pytest.fixture
def renamed(monkeypatch):
    """Pretend an update replaced EXE with NEW_EXE in the same folder."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", NEW_EXE)
    monkeypatch.setattr(startup.os.path, "exists", lambda path: path == NEW_EXE)


def test_after_a_rename_start_with_windows_follows_the_new_exe(renamed):
    startup.winreg.CreateKey(startup.winreg.HKEY_CURRENT_USER, startup.RUN_KEY).values["SteamStatsTracker"] = f'"{EXE}" --tray'
    assert not startup.is_on()
    assert startup.follow_renamed_exe() is True
    assert run_list() == {"SteamStatsTracker": f'"{NEW_EXE}" --tray'}
    assert startup.is_on()
    assert startup.follow_renamed_exe() is False  # nothing left to fix


def test_a_rename_doesnt_switch_it_on(renamed):
    assert startup.follow_renamed_exe() is False
    assert run_list() == {}


def test_a_copy_in_another_folder_keeps_its_setting(renamed):
    other = r'"D:\Games\Steam Stats Tracker\SteamStatsTracker.exe" --tray'
    startup.winreg.CreateKey(startup.winreg.HKEY_CURRENT_USER, startup.RUN_KEY).values["SteamStatsTracker"] = other
    assert startup.follow_renamed_exe() is False
    assert run_list() == {"SteamStatsTracker": other}


def test_an_old_exe_that_is_still_there_is_left_alone(renamed, monkeypatch):
    monkeypatch.setattr(startup.os.path, "exists", lambda path: True)
    startup.winreg.CreateKey(startup.winreg.HKEY_CURRENT_USER, startup.RUN_KEY).values["SteamStatsTracker"] = f'"{EXE}" --tray'
    assert startup.follow_renamed_exe() is False


def test_a_switch_off_in_task_manager_survives_the_rename(renamed):
    registry = startup.winreg
    registry.CreateKey(registry.HKEY_CURRENT_USER, startup.RUN_KEY).values["SteamStatsTracker"] = f'"{EXE}" --tray'
    registry.CreateKey(registry.HKEY_CURRENT_USER, startup.APPROVED_KEY).values["SteamStatsTracker"] = bytes([3]) + bytes(11)
    assert startup.follow_renamed_exe() is True
    assert not startup.is_on()  # still switched off, as the user left it


def test_from_source_nothing_is_followed():
    startup.winreg.CreateKey(startup.winreg.HKEY_CURRENT_USER, startup.RUN_KEY).values["SteamStatsTracker"] = f'"{EXE}" --tray'
    assert startup.follow_renamed_exe() is False
