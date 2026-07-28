"""Validate the reminders block in the shipped appliance_profiles.json."""
import json
import os

from reminder_engine import reminder_device_names

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "appliance_profiles.json")


def _load():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def test_reminders_block_present_and_valid():
    cfg = json.load(open(CONFIG_PATH))
    reminders = cfg["reminders"]
    assert reminders["enabled"] is True
    assert reminders["tv_weekday_daytime"]["device"] == "television"
    assert reminders["tv_weekday_daytime"]["min_continuous_minutes"] == 60
    office = reminders["office_evening"]
    assert office["device"] == "office"
    band_names = [b["name"] for b in office["bands"]]
    assert band_names == ["printer", "pc"]


def test_reminder_devices_are_television_and_office():
    cfg = json.load(open(CONFIG_PATH))
    assert reminder_device_names(cfg["reminders"]) == ["television", "office"]
