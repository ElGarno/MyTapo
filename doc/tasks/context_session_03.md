# Context Session 03 - Tapo KLAP Session Auto-Recovery

## Project Goal
Fix recurring issue where Tapo devices become unreachable due to expired KLAP sessions, requiring manual Tapo app interaction to recover.

## Current Status
- **Phase**: completed
- **Last Updated**: 2026-04-09
- **Blockers**: None - deployed, needs monitoring in production

## Tasks
- [x] Diagnose KLAP session expiry issue (InvalidResponse, 403 Forbidden, SessionTimeout)
- [x] Implement TapoClientManager with automatic re-authentication
- [x] Set failure threshold to 2+ devices (per user request)
- [x] Add periodic client recreation every 30 minutes
- [x] Commit and push (`d7ce928`)
- [x] Fix washing/dryer alert scripts - same KLAP session expiry issue
- [x] Refactor to fresh device handle per cycle (matching influx_consumption pattern)
- [x] Commit and push (`342c61d`, `bd865b4`)

## Progress Log
### 2026-03-30
- Diagnosed: ApiClient created once at startup, KLAP sessions expire over time
- Implemented `TapoClientManager` class in `tapo_influx_consumption_dynamic.py`
  - Recreates ApiClient when 2+ devices fail in a single polling cycle
  - Preventive recreation every 30 minutes
  - Logs all re-authentication events
- Initially used 30% threshold, user requested absolute threshold of 2 devices
- Committed and pushed to main

### 2026-04-09
- Washing/Dryer containers had same KLAP session expiry issue (not covered by d7ce928)
- Root cause: `monitor_power_and_notify_enhanced()` held a single device handle forever, unlike `tapo_influx_consumption_dynamic.py` which calls `client.p110(ip)` each cycle
- First attempt: added auth-error detection + reconnect loop in callers (`342c61d`)
- Still failing - compared with working influx_consumption pattern
- Final fix: changed `monitor_power_and_notify_enhanced()` signature from `device` to `client + device_ip`, gets fresh device handle every 20s cycle (`bd865b4`)
- Key insight: `client.p110(ip)` per cycle prevents stale KLAP sessions entirely, no error recovery needed

## Open Questions
- Does the fresh-handle-per-cycle approach resolve the issue reliably for washing/dryer?
- Is 30 minutes still the right interval for preventive client recreation in influx_consumption?

## Files Modified
- `tapo_influx_consumption_dynamic.py` - added TapoClientManager, failure tracking, auto re-auth (session 03a)
- `utils.py` - changed `monitor_power_and_notify_enhanced()` to use client+IP instead of static device handle
- `washing_machine_alert.py` - passes client+IP instead of pre-created device handle
- `washing_dryer_alert.py` - passes client+IP instead of pre-created device handle

## Agent Outputs Referenced
- None