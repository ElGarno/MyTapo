# Energy Reminders (TV & Office Nudges) — Design

**Date:** 2026-07-28
**Status:** Approved (pending spec review)

## Goal

Add two behavioral-nudge Pushover alerts on top of the existing energy monitoring:

1. **TV weekday daytime**: On weekdays (Mon–Fri), if the TV runs continuously for
   ≥ 1 hour while it is still before 20:00 → send a Pushover reminder.
2. **Office evening**: Every day after 20:00, based on the `office` plug power
   (baseline ~5W):
   - **15W ≤ power < 50W** → printer still on → *smaller* alert
   - **power ≥ 50W** → PC still on → *bigger* alert

Each rule fires at most **once per day**.

## Approach

Extend the existing `event_detector.py` service (chosen over a new standalone
container or an n8n workflow). It already polls all device power from InfluxDB every
15s, tracks TV sessions, and has Pushover wired in — the lowest-overhead, most
architecture-consistent home for these rules.

## Components

### 1. Config — `config/appliance_profiles.json`

New top-level `reminders` block. All tunable numbers/texts live here so thresholds
can be adjusted with only a container restart (no rebuild):

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
      {"name": "pc",      "min_watt": 50, "max_watt": null, "priority": 1, "message": "Rechner läuft noch im Office!"}
    ]
  }
}
```

Boundary rule: a band matches `min_watt <= power < max_watt` (`max_watt: null` = open
ended). So exactly 50W → PC band. Bands are evaluated in order; first match wins.

### 2. `ReminderEngine` (new class in `event_detector.py`)

Pure logic, no I/O — takes power readings + current time, returns/sends reminders.
Easily unit-testable.

**State:**
- `tv_on_since: Optional[datetime]` — when the TV first went continuously ≥ threshold_on
  (reset to None when power < threshold_off).
- `last_fired: Dict[str, date]` — keys `"tv"`, `"office_printer"`, `"office_pc"`.
- `office_band_streak: Dict[str, int]` — consecutive in-band reading counter per band
  (for `sustained_readings`).

**`evaluate(power_data: Dict[str, tuple[float, datetime]], now: datetime)`** — called
each poll cycle:

*TV logic:*
- Read `television` power. If ≥ `threshold_on`, set `tv_on_since` if not already set. If
  < `threshold_off`, clear `tv_on_since`.
- If `tv_on_since` set and continuous duration ≥ `min_continuous_minutes` AND
  `weekdays_only ⇒ now.weekday() < 5` AND `now.hour < before_hour` AND not already fired
  today → fire TV reminder.

*Office logic:*
- Gate on `now.hour >= after_hour` and (if `weekdays_only`) weekday.
- Read `office` power. Find first matching band. Increment that band's streak, reset the
  other bands' streaks. If streak ≥ `sustained_readings` AND band not fired today → fire.
- If no band matches (e.g. < 15W), reset all office streaks.

**`_fire(key, message, priority, now)`** — dedup check via `last_fired[key] == now.date()`,
else `send_pushover_notification_new(user, message, priority=...)` and record the date.

### 3. Wiring in `EventDetectorService`

- Load `reminders` config in `_load_profiles` (or a new `_load_reminders`).
- Instantiate `ReminderEngine(reminders_config, self.pushover_user)` in `__init__`.
- Extend `_query_latest_power` device list to include reminder devices not already
  profiled (i.e. add `office`). `television` is already profiled.
- In `run()` loop, after detector processing, call
  `self.reminder_engine.evaluate(power_data, datetime.now())`.

### 4. Pushover priority — `utils.send_pushover_notification_new`

Extend signature minimally: `send_pushover_notification_new(user, message, priority=0,
title=None, sound=None)`. Add `priority`/`title`/`sound` to the POST params only when set.
Backward compatible (existing callers pass two args). PC alert uses `priority=1` (high) +
a distinct sound; printer uses default.

## Data Flow

InfluxDB `power_consumption` → `_query_latest_power` (now incl. `office`) → per-cycle
`ReminderEngine.evaluate()` → dedup → Pushover. No new InfluxDB writes; reminders are
transient nudges, not logged events.

## Error Handling

- Missing device in `power_data` (e.g. `office` offline): skip that rule this cycle, no
  crash. Engine reads defensively with `.get()`.
- Engine exceptions must not break the detection loop — wrap the `evaluate()` call
  (the loop already has a top-level try/except; keep engine failures non-fatal and logged).
- `reminders.enabled == false` or missing config → engine is a no-op.

## Testing

`pytest` unit tests for `ReminderEngine` (pure logic, no InfluxDB/Pushover — inject a fake
send callback and feed synthetic `(power, timestamp)` sequences):

- TV reaches 1h continuous on a weekday before 20:00 → fires once.
- TV reaches 1h on a weekend → does not fire.
- TV reaches 1h but only after 20:00 → does not fire.
- TV drops below `threshold_off` mid-session → timer resets, no premature fire.
- Office 23W after 20:00 (sustained) → printer alert, priority 0.
- Office 120W after 20:00 (sustained) → PC alert, priority 1.
- Office 40W → printer band (15–50).
- Office 10W → no alert.
- Office band met before 20:00 → no alert.
- Sustained gate: single in-band reading (< `sustained_readings`) → no fire yet.
- Dedup: condition true across many cycles same day → exactly one Pushover per rule.
- Dedup resets next day.

## Deployment

`event_detector` runs as image `faffi86/mytapo-event_detector:latest`. Shipping =
rebuild image (config baked in via `Dockerfile.event_detector`) + push + redeploy stack
in Portainer. No live config reload in this service (config read once at startup);
threshold tuning after go-live = edit config + restart container.

## Out of Scope (YAGNI)

- No generic rule DSL — two dedicated rule evaluators only.
- No AWTRIX output for these reminders (Pushover only, per request).
- No InfluxDB logging of reminder firings.
- No `office2` inclusion (only `office`).
