# Energy Reminders (TV & Office Nudges) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two behavioral-nudge Pushover alerts (weekday-daytime TV overuse, evening office printer/PC left on) to the existing `event_detector` service.

**Architecture:** A new pure-logic `ReminderEngine` class (own module) is fed the per-cycle power readings the `event_detector` already queries from InfluxDB, evaluates two config-driven rules against the current time, and fires deduplicated Pushover messages. No new container, no new InfluxDB writes.

**Tech Stack:** Python 3.13, uv, pytest, InfluxDB (existing), Pushover (existing), Docker (`faffi86/mytapo-event_detector`).

## Global Constraints

- Python `>=3.13`; package/dep management via `uv`.
- Code, comments, docstrings in English.
- Reminders are **Pushover only** — no AWTRIX output.
- All thresholds/hours/messages live in `config/appliance_profiles.json` (tunable via restart, no rebuild).
- Each rule fires **at most once per calendar day** (dedup by `now.date()`).
- Only the `office` device is used (never `office2`).
- `ReminderEngine` must have **no heavy imports** (stdlib only) so tests stay isolated; the Pushover send function is injected.
- `ReminderEngine.evaluate()` must never raise into the detection loop (catch + log internally).

---

### Task 1: Test tooling + Pushover priority/title/sound

**Files:**
- Modify: `pyproject.toml` (add dev group + pytest config)
- Modify: `utils.py:23-62` (`send_pushover_notification_new`)
- Test: `tests/test_pushover_params.py`

**Interfaces:**
- Produces: `send_pushover_notification_new(user, message, priority=0, title=None, sound=None) -> bool` — optional params are added to the POST body only when truthy. Backward compatible with existing two-arg callers.

- [ ] **Step 1: Add pytest tooling to `pyproject.toml`**

Append these two blocks to `pyproject.toml`:

```toml
[dependency-groups]
dev = ["pytest>=8.3"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_pushover_params.py`:

```python
"""Tests for optional Pushover parameters (priority/title/sound)."""
import http.client


class _FakeResponse:
    status = 200

    def read(self):
        return b'{"status":1}'


class _FakeConn:
    last_body = None

    def __init__(self, *args, **kwargs):
        pass

    def request(self, method, path, body, headers):
        _FakeConn.last_body = body

    def getresponse(self):
        return _FakeResponse()

    def close(self):
        pass


def _patch(monkeypatch):
    _FakeConn.last_body = None
    monkeypatch.setenv("PUSHOVER_TAPO_API_TOKEN", "tok")
    monkeypatch.setattr(http.client, "HTTPSConnection", _FakeConn)


def test_priority_and_sound_included_when_set(monkeypatch):
    _patch(monkeypatch)
    from utils import send_pushover_notification_new

    ok = send_pushover_notification_new("user1", "hi", priority=1, sound="siren")

    assert ok is True
    assert "priority=1" in _FakeConn.last_body
    assert "sound=siren" in _FakeConn.last_body


def test_optional_params_omitted_by_default(monkeypatch):
    _patch(monkeypatch)
    from utils import send_pushover_notification_new

    send_pushover_notification_new("user1", "hi")

    assert "priority=" not in _FakeConn.last_body
    assert "sound=" not in _FakeConn.last_body
    assert "title=" not in _FakeConn.last_body
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_pushover_params.py -v`
Expected: FAIL — `test_priority_and_sound_included_when_set` errors because `send_pushover_notification_new()` got an unexpected keyword argument `priority`.

- [ ] **Step 4: Implement the util change**

In `utils.py`, change the signature and body of `send_pushover_notification_new`. Replace the signature line and the `conn.request(...)` block:

```python
def send_pushover_notification_new(user, message, priority=0, title=None, sound=None):
    load_dotenv()
    pushover_api_token = os.getenv("PUSHOVER_TAPO_API_TOKEN")

    if not pushover_api_token:
        logger.error("PUSHOVER_TAPO_API_TOKEN environment variable not set")
        return False

    if not user or not message:
        logger.error(f"Missing required parameters: user={bool(user)}, message={bool(message)}")
        return False

    try:
        conn = http.client.HTTPSConnection("api.pushover.net:443")
        params = {
            "token": pushover_api_token,
            "user": user,
            "message": message,
        }
        if priority:
            params["priority"] = priority
        if title:
            params["title"] = title
        if sound:
            params["sound"] = sound
        conn.request("POST", "/1/messages.json",
                     urllib.parse.urlencode(params),
                     {"Content-type": "application/x-www-form-urlencoded"})

        response = conn.getresponse()
        response_data = response.read().decode()

        if response.status == 200:
            logger.info(f"Pushover notification sent successfully: {message[:50]}...")
            return True
        else:
            logger.error(f"Pushover API error {response.status}: {response_data}")
            return False

    except Exception as e:
        logger.error(f"Failed to send Pushover notification: {e}")
        return False
    finally:
        try:
            conn.close()
        except:
            pass
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_pushover_params.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml utils.py tests/test_pushover_params.py
git commit -m "feat(utils): add optional priority/title/sound to Pushover helper"
```

---

### Task 2: ReminderEngine module + TV rule

**Files:**
- Create: `reminder_engine.py`
- Test: `tests/test_reminder_engine_tv.py`

**Interfaces:**
- Produces: `reminder_device_names(reminders: dict) -> list[str]` — device names referenced by enabled rules.
- Produces: `ReminderEngine(config: dict, pushover_user, send_fn)` with `evaluate(power_data: dict[str, tuple[float, datetime]], now: datetime) -> None`. `send_fn` is called as `send_fn(user, message, priority=<int>, sound=<str|None>)`.

- [ ] **Step 1: Write the failing TV tests**

Create `tests/test_reminder_engine_tv.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_reminder_engine_tv.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reminder_engine'`.

- [ ] **Step 3: Create `reminder_engine.py` with the helper, class, and TV logic**

Create `reminder_engine.py`:

```python
"""
Behavioral-nudge reminder engine for MyTapo.

Pure logic (stdlib only): fed the latest power readings and the current time each
cycle, evaluates config-driven rules, and fires deduplicated Pushover messages via
an injected send function. See docs/superpowers/specs/2026-07-28-energy-reminders-design.md.
"""
import logging
from datetime import date, datetime
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reminder_engine_tv.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add reminder_engine.py tests/test_reminder_engine_tv.py
git commit -m "feat(reminders): add ReminderEngine with TV weekday-daytime rule"
```

---

### Task 3: Office printer/PC evening rule

**Files:**
- Modify: `reminder_engine.py` (already implements office logic from Task 2 — this task adds its tests and verifies)
- Test: `tests/test_reminder_engine_office.py`

**Interfaces:**
- Consumes: `ReminderEngine` and its `office_evening` config shape (bands with `min_watt`/`max_watt`/`priority`/`sound`/`message`).

> Note: the office logic was written in Task 2's `reminder_engine.py`. This task locks it in with dedicated tests. If any test fails, fix `_evaluate_office` in `reminder_engine.py`.

- [ ] **Step 1: Write the failing office tests**

Create `tests/test_reminder_engine_office.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_reminder_engine_office.py -v`
Expected: PASS (8 passed). The office logic already exists from Task 2; these tests confirm it. If any fail, fix `_evaluate_office` in `reminder_engine.py` and re-run.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (all tests from Tasks 1-3).

- [ ] **Step 4: Commit**

```bash
git add tests/test_reminder_engine_office.py
git commit -m "test(reminders): cover office evening printer/PC bands"
```

---

### Task 4: Config block + wire ReminderEngine into event_detector

**Files:**
- Modify: `config/appliance_profiles.json` (add `reminders` block)
- Modify: `event_detector.py` (import, load config, instantiate engine, extend power query, call in loop)
- Test: `tests/test_reminders_config.py`

**Interfaces:**
- Consumes: `reminder_device_names`, `ReminderEngine` (Task 2); `send_pushover_notification_new` (Task 1).

- [ ] **Step 1: Add the `reminders` block to `config/appliance_profiles.json`**

Inside the top-level object, add a sibling key to `"profiles"` and `"settings"` (i.e. add `"reminders": {...}` after the `"settings"` object's closing brace, with a comma). The block:

```json
"reminders": {
  "enabled": true,
  "tv_weekday_daytime": {
    "enabled": true,
    "device": "television",
    "threshold_on": 30,
    "threshold_off": 20,
    "min_continuous_minutes": 60,
    "weekdays_only": true,
    "before_hour": 20,
    "priority": 0,
    "message": "Unter der Woche Fernsehzeit wollten wir reduzieren"
  },
  "office_evening": {
    "enabled": true,
    "device": "office",
    "after_hour": 20,
    "weekdays_only": false,
    "sustained_readings": 3,
    "bands": [
      {"name": "printer", "min_watt": 15, "max_watt": 50, "priority": 0, "message": "Drucker läuft noch im Office"},
      {"name": "pc", "min_watt": 50, "max_watt": null, "priority": 1, "sound": "siren", "message": "Rechner läuft noch im Office!"}
    ]
  }
}
```

- [ ] **Step 2: Write the failing config test**

Create `tests/test_reminders_config.py`:

```python
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
```

- [ ] **Step 3: Run the config test to verify it passes**

Run: `uv run pytest tests/test_reminders_config.py -v`
Expected: PASS (2 passed). (Config was added in Step 1; this asserts it.)

- [ ] **Step 4: Wire the engine into `event_detector.py`**

4a. Add imports near the top (after line 21, `from utils import send_pushover_notification_new`):

```python
from reminder_engine import ReminderEngine, reminder_device_names
```

4b. In `_load_profiles` (around line 220-222), after `self.settings = config.get("settings", {})`, add:

```python
                self.reminders = config.get("reminders", {})
```

4c. In `__init__`, after `self._initialize_detectors()` (line 207), add:

```python
        self.reminder_engine = ReminderEngine(
            self.reminders, self.pushover_user, send_pushover_notification_new
        )
        logger.info(f"Reminder devices: {reminder_device_names(self.reminders)}")
```

4d. In `_query_latest_power` (line 420), replace:

```python
        device_names = list(self.profiles.keys())
```

with:

```python
        device_names = list(self.profiles.keys())
        for name in reminder_device_names(self.reminders):
            if name not in device_names:
                device_names.append(name)
```

4e. In `run()` (after the detector `for` loop that ends at line 671, before `await self._send_summary()` at line 674), add:

```python
                # Evaluate behavioral-nudge reminders (never raises)
                self.reminder_engine.evaluate(power_data, datetime.now())
```

- [ ] **Step 5: Smoke-test the wiring (import + construct without InfluxDB)**

Run:

```bash
uv run python -c "
import json, event_detector
from reminder_engine import ReminderEngine, reminder_device_names
cfg = json.load(open('config/appliance_profiles.json'))
eng = ReminderEngine(cfg['reminders'], 'u', lambda *a, **k: True)
from datetime import datetime
eng.evaluate({'office': (120, datetime.now()), 'television': (120, datetime.now())}, datetime.now())
print('devices:', reminder_device_names(cfg['reminders']))
print('event_detector import OK')
"
```

Expected: prints `devices: ['television', 'office']` and `event_detector import OK`, no traceback.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (all tests).

- [ ] **Step 7: Commit**

```bash
git add config/appliance_profiles.json event_detector.py tests/test_reminders_config.py
git commit -m "feat(reminders): wire ReminderEngine into event_detector + config"
```

---

## Deployment (after all tasks pass, manual)

1. Rebuild the event_detector image (config is baked in via `Dockerfile.event_detector`):
   `docker build -f Dockerfile.event_detector -t faffi86/mytapo-event_detector:latest .`
2. Push: `docker push faffi86/mytapo-event_detector:latest`
3. Redeploy the stack in Portainer. **IMPORTANT:** the `config` mount is a *named
   Docker volume* — an existing volume shadows the image-baked
   `appliance_profiles.json`, so a plain image bump would leave the container reading
   the OLD config (no `reminders` key → engine silently no-ops). The usual Portainer
   flow (delete stack → recreate) recreates the volume fresh and picks up the new
   config, so it's fine; just don't skip the volume refresh. Alternatively inject the
   new config live via `docker exec` (as with device edits).
4. Verify in logs: `Reminder devices: ['television', 'office']` on startup, and
   `Reminder fired [...]` when a rule triggers.

Threshold tuning after go-live: edit `config/appliance_profiles.json` in the container
and restart (no code change / rebuild).

**Timezone note:** the rules gate on `datetime.now()` local wall-clock (before/after
20:00), same as the existing daily-summary logic. Ensure the `event_detector` container's
timezone is Europe/Berlin (as it already must be for the daily summary at 21:05 to fire
correctly) — otherwise "after 20:00" would be evaluated in UTC.
