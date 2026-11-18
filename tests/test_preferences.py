"""preferences.py: the settings settings.exe changes."""

import pytest

import config
import preferences
import storage


def test_defaults_come_from_config():
    assert preferences.current() == {"keep_running": config.KEEP_RUNNING_DEFAULT}


def test_a_change_is_saved():
    preferences.update(keep_running=False)
    assert preferences.keep_running() is False
    preferences.update(keep_running=True)
    assert preferences.keep_running() is True


@pytest.mark.parametrize("change", [{"keep_running": "yes"}, {"no_such_setting": True}])
def test_junk_is_refused(change):
    with pytest.raises(ValueError):
        preferences.update(**change)


@pytest.mark.parametrize("saved", ["not json", "[1, 2]", '{"keep_running": "yes"}'])
def test_a_broken_saved_value_falls_back_to_the_defaults(saved):
    storage.set_setting(preferences.SETTING, saved)
    assert preferences.current() == preferences.defaults()


def test_the_tray_notice_is_only_shown_the_first_time():
    assert preferences.first_time_hidden() is True
    assert preferences.first_time_hidden() is False
