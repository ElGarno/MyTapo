"""Tests for espresso/coffee session grouping in ApplianceEventDetector.

Real data showed one coffee making (espresso + milk frothing, or a double shot)
produces multiple ~1600W pulses separated by 1-2.5 min gaps, which the old 30s
off-confirmation split into 2-3 separate events. These tests pin the fix: pulses
within a session's off-confirmation window collapse into ONE event, with the
duration reflecting actual activity (not the confirmation wait).
"""
from datetime import datetime, timedelta

from event_detector import ApplianceEventDetector

BASE = datetime(2026, 8, 3, 11, 0, 0)


def _t(sec):
    return BASE + timedelta(seconds=sec)


def _profile():
    return {
        "event_name": "espresso",
        "event_name_plural": "espressos",
        "detection_type": "spike",
        "threshold_on": 800,
        "threshold_off": 50,
        "min_duration_seconds": 20,
        "max_duration_seconds": 900,
        "cooldown_seconds": 60,
        "off_confirmation_seconds": 180,
        "track_duration": True,
        "track_energy": True,
    }


def _settings():
    return {"cooling_confirmation_seconds": 30}


def _feed(det, readings):
    events = []
    for power, t in readings:
        ev = det.process_reading(power, t)
        if ev:
            events.append(ev)
    return events


def _quiet(start, stop, step=20):
    return [(2, _t(s)) for s in range(start, stop, step)]


def test_multi_pulse_cappuccino_is_one_event():
    """3 pulses ~2min apart (extraction + froth + double) -> ONE event."""
    det = ApplianceEventDetector("kaffe_bar", _profile(), _settings())
    readings = []
    readings += [(1600, _t(0)), (1600, _t(20)), (2, _t(40))]      # pulse 1
    readings += _quiet(60, 120)                                    # 80s gap
    readings += [(1600, _t(120)), (1600, _t(140)), (2, _t(160))]  # pulse 2
    readings += _quiet(180, 240)                                   # 80s gap
    readings += [(1600, _t(240)), (1600, _t(260)), (2, _t(280))]  # pulse 3
    readings += _quiet(300, 520)                                   # >180s -> finalize
    events = _feed(det, readings)
    assert len(events) == 1
    assert events[0].event_type == "espresso"


def test_session_duration_not_inflated_by_off_confirmation():
    """A single ~40s espresso should report ~40s, not 40s + 180s wait."""
    det = ApplianceEventDetector("kaffe_bar", _profile(), _settings())
    readings = [(1600, _t(0)), (1600, _t(20)), (2, _t(40))] + _quiet(60, 300)
    events = _feed(det, readings)
    assert len(events) == 1
    # Duration is from first pulse (0s) to the drop (40s), not the 180s confirmation.
    assert events[0].duration_seconds <= 60


def test_two_separate_sessions_stay_two_events():
    """Two makings 10 min apart remain two distinct events."""
    det = ApplianceEventDetector("kaffe_bar", _profile(), _settings())
    readings = []
    readings += [(1600, _t(0)), (1600, _t(20)), (2, _t(40))]       # session A
    readings += _quiet(60, 400)                                     # long quiet -> A finalizes
    readings += [(1600, _t(600)), (1600, _t(620)), (2, _t(640))]   # session B, 10 min later
    readings += _quiet(660, 880)                                    # finalize B
    events = _feed(det, readings)
    assert len(events) == 2


def test_other_appliances_use_global_confirmation():
    """A profile without off_confirmation_seconds falls back to the 30s global."""
    profile = _profile()
    del profile["off_confirmation_seconds"]
    det = ApplianceEventDetector("kaffe_bar", profile, _settings())
    readings = []
    readings += [(1600, _t(0)), (1600, _t(20)), (2, _t(40))]       # pulse 1
    readings += _quiet(60, 120)                                     # 80s gap > 30s global
    readings += [(1600, _t(120)), (1600, _t(140)), (2, _t(160))]   # pulse 2
    readings += _quiet(180, 400)
    events = _feed(det, readings)
    # With the 30s global confirmation, the 80s gap splits into two events (old behavior).
    assert len(events) == 2
