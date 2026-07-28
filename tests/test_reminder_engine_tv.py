"""Tests for the TV weekday-daytime reminder rule."""
from datetime import datetime, timedelta

from reminder_engine import ReminderEngine, reminder_device_names

# 2026-07-28 is a Tuesday (weekday); 2026-08-01 is a Saturday (weekend).
TUESDAY = datetime(2026, 7, 28, 18, 0, 0)
SATURDAY = datetime(2026, 8, 1, 18, 0, 0)


class FakeSender:
    def __init__(self):
        self.calls = []

    def __call__(self, user, message, priority=0, title=None, sound=None):
        self.calls.append({"message": message, "priority": priority, "sound": sound})
        return True


def _config():
    return {
        "enabled": True,
        "tv_weekday_daytime": {
            "enabled": True,
            "device": "television",
            "threshold_on": 30,
            "threshold_off": 20,
            "min_continuous_minutes": 60,
            "weekdays_only": True,
            "before_hour": 20,
            "priority": 0,
            "message": "Unter der Woche Fernsehzeit wollten wir reduzieren",
        },
    }


def test_reminder_device_names_lists_television():
    assert reminder_device_names(_config()) == ["television"]


def test_tv_fires_once_after_one_hour_on_weekday_before_20():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    t0 = TUESDAY  # 18:00
    eng.evaluate({"television": (120, t0)}, t0)          # starts timer, duration 0
    assert s.calls == []
    t1 = t0 + timedelta(minutes=61)                       # 19:01, still Tuesday <20
    eng.evaluate({"television": (120, t1)}, t1)
    assert len(s.calls) == 1
    assert s.calls[0]["message"] == "Unter der Woche Fernsehzeit wollten wir reduzieren"
    assert s.calls[0]["priority"] == 0


def test_tv_does_not_fire_on_weekend():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    t0 = SATURDAY
    eng.evaluate({"television": (120, t0)}, t0)
    t1 = t0 + timedelta(minutes=61)
    eng.evaluate({"television": (120, t1)}, t1)
    assert s.calls == []


def test_tv_does_not_fire_after_20():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    t0 = datetime(2026, 7, 28, 19, 30, 0)                 # Tuesday 19:30
    eng.evaluate({"television": (120, t0)}, t0)
    t1 = t0 + timedelta(minutes=61)                       # 20:31 -> hour 20, not < 20
    eng.evaluate({"television": (120, t1)}, t1)
    assert s.calls == []


def test_tv_timer_resets_when_power_drops():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    t0 = TUESDAY
    eng.evaluate({"television": (120, t0)}, t0)            # timer start
    t_off = t0 + timedelta(minutes=30)
    eng.evaluate({"television": (5, t_off)}, t_off)        # below threshold_off -> reset
    t1 = t0 + timedelta(minutes=61)                        # 61 min since ORIGINAL start
    eng.evaluate({"television": (120, t1)}, t1)            # only ~31 min since reset
    assert s.calls == []


def test_tv_fires_only_once_same_day():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    t0 = TUESDAY
    eng.evaluate({"television": (120, t0)}, t0)
    for extra in (61, 62, 90, 120):
        t = t0 + timedelta(minutes=extra)
        eng.evaluate({"television": (120, t)}, t)
    assert len(s.calls) == 1
