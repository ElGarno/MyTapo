# Context Session 01 - Solarbank Custom Schedule Optimization

## Project Goal
Analyze historical power consumption data from InfluxDB to create an optimized hourly usage profile for the Anker Solarbank 2 E1600 Plus custom mode. The goal is to identify high-consumption hours throughout the day to maximize solar self-consumption.

## Important Constraints
- **Exclude cooking times**: The induction cooktop (Kochfeld) is on a high-voltage connection and not tracked by Tapo plugs, but its usage causes significant spikes that should NOT influence the solar schedule.
  - Lunch: ~12:30
  - Dinner: ~18:00 - 19:30
- These time windows may show artificially lower consumption (since the cooktop isn't tracked), but the actual household load is high during these times.

## Current Status
- **Phase**: implementation (ready to test)
- **Last Updated**: 2026-03-06
- **Blockers**: Need to run script from home network (InfluxDB access)

## Tasks
- [x] Create doc/ structure and session context
- [x] Explore InfluxDB data schema (measurements, fields, tags for consumption data)
- [x] Query historical consumption data grouped by hour-of-day
- [x] Aggregate across all tracked devices (sum per hour)
- [x] Average across all available days
- [x] Visualize hourly consumption profile
- [x] Identify high-consumption hours for Solarbank custom schedule
- [x] Account for untracked cooking times in recommendations
- [ ] Run script and validate results
- [ ] Fine-tune cooking boost values if needed

## Progress Log
### 2026-03-06
- Session initialized
- Task defined: Optimize Anker Solarbank 2 E1600 Plus custom mode schedule
- Created doc/ structure and session context
- Explored codebase: InfluxDB schema uses bucket `power_consumption`, measurement `power_consumption`, tag `device`, field `power`
- Created `solarbank_schedule_optimizer.py` with:
  - Flux query for hourly average profile (+ Python fallback)
  - Cooking time boost for untracked induction cooktop
  - Solarbank schedule clamped to 0-800W
  - Chart visualization (matplotlib)
  - App-friendly output format for Anker app

## Key Decisions
- Solar device excluded from consumption sum (it's generation)
- Cooking boosts: lunch 800W (12:00-13:30), dinner 1200W (17:30-19:30)
- Analysis window: 90 days for stable averages
- Solarbank max output: 800W (E1600 Plus spec)

## Open Questions
- Are the cooking boost values (800W lunch, 1200W dinner) realistic?
- How many days of data are actually available in InfluxDB?
- Does the Solarbank app accept hourly or finer granularity?

## Files Modified
- `doc/tasks/context_session_01.md` - created
- `doc/` directory structure - created
- `solarbank_schedule_optimizer.py` - created (main script)

## Agent Outputs Referenced
- None yet