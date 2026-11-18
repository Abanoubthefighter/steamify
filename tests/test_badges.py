"""badges.py: the running total and the badges it earns."""

import config
import badges
import storage

HOUR = 3600


def test_the_ladder_follows_config():
    assert [badge["key"] for badge in badges.ladder(0)] == [key for key, _, _ in config.BADGES]
    assert not any(badge["earned"] for badge in badges.ladder(0))


def test_current_and_next():
    assert badges.current(0) is None
    first_hours = config.BADGES[0][2]
    halfway = first_hours * HOUR // 2
    assert badges.next_up(halfway)["key"] == "dialup" and badges.next_up(halfway)["percent"] == 50
    assert badges.next_up(halfway)["minutes_left"] == first_hours * 30
    assert badges.current(first_hours * HOUR)["key"] == "dialup"
    # the second step counts from the first badge, not from zero
    second = config.BADGES[1][2]
    assert badges.next_up(first_hours * HOUR)["percent"] == 0
    assert badges.next_up(second * HOUR - 1)["minutes_left"] == 1
    assert badges.next_up(config.BADGES[-1][2] * HOUR) is None


def test_newly_earned():
    six = config.BADGES[0][2] * HOUR
    assert [badge["key"] for badge in badges.newly_earned(six - 60, six)] == ["dialup"]
    assert badges.newly_earned(six, six + 60) == []


def test_the_running_total_adds_up_and_survives_junk():
    assert badges.add_running(90) == (0, 90)
    assert badges.add_running(30.7) == (90, 120)
    storage.set_setting(badges.RUNNING, "junk")
    assert badges.running_seconds() == 0


def test_a_new_badge_is_unseen_until_marked():
    badges.add_running(config.BADGES[0][2] * HOUR)
    assert badges.unseen()["key"] == "dialup"
    badges.mark_seen("dialup")
    assert badges.unseen() is None
    badges.mark_seen("not a badge")  # ignored
    assert storage.get_setting(badges.SEEN) == "dialup"


class FakeTime:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def test_the_clock_counts_running_time_but_not_sleep():
    clock_time = FakeTime()
    clock = badges.RunningClock(clock=clock_time)
    clock._last = clock_time()  # as start() would, without the thread
    clock_time.now += 60
    clock.tick()
    assert badges.running_seconds() == 60
    clock_time.now += 8 * HOUR  # the laptop slept the night
    clock.tick()
    assert badges.running_seconds() == 60 + config.RUNNING_TICK_SECONDS
    clock_time.now += 20
    clock.stop()  # the last part-minute counts too
    assert badges.running_seconds() == 60 + config.RUNNING_TICK_SECONDS + 20


def test_the_clock_says_when_a_badge_is_earned():
    earned = []
    clock_time = FakeTime()
    clock = badges.RunningClock(on_badge=earned.append, clock=clock_time)
    clock._last = clock_time()
    badges.add_running(config.BADGES[0][2] * HOUR - 30)
    clock_time.now += 60
    clock.tick()
    assert [badge["key"] for badge in earned] == ["dialup"]
