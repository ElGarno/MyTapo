"""Tests for the office evening printer/PC reminder rule."""
from datetime import datetime, timedelta

from reminder_engine import ReminderEngine

TUES_EVENING = datetime(2026, 7, 28, 21, 0, 0)   # Tuesday 21:00 (after 20)
TUES_DAYTIME = datetime(2026, 7, 28, 15, 0, 0)   # Tuesday 15:00 (before 20)


class FakeSender:
    def __init__(self):
        self.calls = []

    def __call__(self, user, message, priority=0, title=None, sound=None):
        self.calls.append({"message": message, "priority": priority, "sound": sound})
        return True


def _config():
    return {
        "enabled": True,
        "office_evening": {
            "enabled": True,
            "device": "office",
            "after_hour": 20,
            "weekdays_only": False,
            "sustained_readings": 3,
            "bands": [
                {"name": "printer", "min_watt": 15, "max_watt": 50, "priority": 0,
                 "message": "Drucker läuft noch im Office"},
                {"name": "pc", "min_watt": 50, "max_watt": None, "priority": 1,
                 "sound": "siren", "message": "Rechner läuft noch im Office!"},
            ],
        },
    }


def _feed(eng, power, start, n):
    """Feed n sustained readings 15s apart, return last timestamp."""
    t = start
    for _ in range(n):
        eng.evaluate({"office": (power, t)}, t)
        t = t + timedelta(seconds=15)
    return t


def test_printer_band_fires_after_sustained_readings():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    _feed(eng, 23, TUES_EVENING, 3)
    assert len(s.calls) == 1
    assert s.calls[0]["message"] == "Drucker läuft noch im Office"
    assert s.calls[0]["priority"] == 0


def test_pc_band_fires_with_high_priority_and_sound():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    _feed(eng, 120, TUES_EVENING, 3)
    assert len(s.calls) == 1
    assert s.calls[0]["message"] == "Rechner läuft noch im Office!"
    assert s.calls[0]["priority"] == 1
    assert s.calls[0]["sound"] == "siren"


def test_40w_is_printer_band():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    _feed(eng, 40, TUES_EVENING, 3)
    assert len(s.calls) == 1
    assert s.calls[0]["message"] == "Drucker läuft noch im Office"


def test_below_15w_never_fires():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    _feed(eng, 5, TUES_EVENING, 5)
    assert s.calls == []


def test_no_fire_before_after_hour():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    _feed(eng, 120, TUES_DAYTIME, 5)
    assert s.calls == []


def test_single_reading_below_sustained_does_not_fire():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    _feed(eng, 120, TUES_EVENING, 2)   # sustained_readings is 3
    assert s.calls == []


def test_office_fires_once_per_day():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    _feed(eng, 120, TUES_EVENING, 20)
    assert len(s.calls) == 1


def test_office_dedup_resets_next_day():
    s = FakeSender()
    eng = ReminderEngine(_config(), "u", s)
    _feed(eng, 120, TUES_EVENING, 3)
    next_day = TUES_EVENING + timedelta(days=1)
    _feed(eng, 120, next_day, 3)
    assert len(s.calls) == 2
