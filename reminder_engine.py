"""
Behavioral-nudge reminder engine for MyTapo.

Pure logic (stdlib only): fed the latest power readings and the current time each
cycle, evaluates config-driven rules, and fires deduplicated Pushover messages via
an injected send function. See docs/superpowers/specs/2026-07-28-energy-reminders-design.md.
"""
import logging
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def reminder_device_names(reminders: dict) -> list:
    """Return device names referenced by enabled reminder rules."""
    names = []
    if not reminders or not reminders.get("enabled", True):
        return names
    tv = reminders.get("tv_weekday_daytime")
    if tv and tv.get("enabled", True) and tv.get("device"):
        names.append(tv["device"])
    office = reminders.get("office_evening")
    if office and office.get("enabled", True) and office.get("device"):
        if office["device"] not in names:
            names.append(office["device"])
    return names


class ReminderEngine:
    """Evaluates time+threshold nudge rules against live power readings."""

    def __init__(self, config: dict, pushover_user: Optional[str], send_fn: Callable):
        self.config = config or {}
        self.pushover_user = pushover_user
        self.send_fn = send_fn
        self.tv_on_since: Optional[datetime] = None
        self.last_fired: dict = {}          # rule_key -> date
        self.office_streak: dict = {}        # band_name -> consecutive in-band count

    def evaluate(self, power_data: dict, now: datetime) -> None:
        """Evaluate all rules for one polling cycle. Never raises."""
        if not self.config.get("enabled", True):
            return
        try:
            self._evaluate_tv(power_data, now)
        except Exception as e:
            logger.error(f"TV reminder evaluation failed: {e}")
        try:
            self._evaluate_office(power_data, now)
        except Exception as e:
            logger.error(f"Office reminder evaluation failed: {e}")

    def _evaluate_tv(self, power_data: dict, now: datetime) -> None:
        tv = self.config.get("tv_weekday_daytime")
        if not tv or not tv.get("enabled", True):
            return
        reading = power_data.get(tv["device"])
        if reading is None:
            return
        power = reading[0]
        if power >= tv["threshold_on"]:
            if self.tv_on_since is None:
                self.tv_on_since = now
        elif power < tv["threshold_off"]:
            self.tv_on_since = None
        if self.tv_on_since is None:
            return
        duration_min = (now - self.tv_on_since).total_seconds() / 60.0
        weekday_ok = now.weekday() < 5 if tv.get("weekdays_only") else True
        before_ok = now.hour < tv["before_hour"]
        if duration_min >= tv["min_continuous_minutes"] and weekday_ok and before_ok:
            self._fire("tv", tv["message"], tv.get("priority", 0), tv.get("sound"), now)

    def _evaluate_office(self, power_data: dict, now: datetime) -> None:
        office = self.config.get("office_evening")
        if not office or not office.get("enabled", True):
            return
        bands = office.get("bands", [])
        weekday_ok = now.weekday() < 5 if office.get("weekdays_only") else True
        in_window = now.hour >= office["after_hour"] and weekday_ok
        reading = power_data.get(office["device"]) if in_window else None
        if not in_window or reading is None:
            for band in bands:
                self.office_streak[band["name"]] = 0
            return
        power = reading[0]
        matched = None
        for band in bands:
            hi = band.get("max_watt")
            if power >= band["min_watt"] and (hi is None or power < hi):
                matched = band
                break
        for band in bands:
            if matched and band["name"] == matched["name"]:
                self.office_streak[band["name"]] = self.office_streak.get(band["name"], 0) + 1
            else:
                self.office_streak[band["name"]] = 0
        if matched and self.office_streak[matched["name"]] >= office.get("sustained_readings", 1):
            self._fire(f"office_{matched['name']}", matched["message"],
                       matched.get("priority", 0), matched.get("sound"), now)

    def _fire(self, key: str, message: str, priority: int, sound: Optional[str], now: datetime) -> None:
        if self.last_fired.get(key) == now.date():
            return
        self.send_fn(self.pushover_user, message, priority=priority, sound=sound)
        self.last_fired[key] = now.date()
        logger.info(f"Reminder fired [{key}] (priority={priority}): {message}")
