# Context Session 02 - Grafana Dashboards & n8n Workflow Fixes

## Project Goal
Create Grafana dashboards for energy monitoring and fix n8n AI workflow issues (tool nodes, memory, Awtrix output).

## Current Status
- **Phase**: testing
- **Last Updated**: 2026-03-09 17:00
- **Blockers**: User needs to reimport dashboards and validate fixes visually

## Tasks

### n8n Workflow Fixes (all committed)
- [x] Fix "Invalid URL" error - migrated from `toolHttpRequest` v1.1 to `httpRequestTool` v4.3
- [x] Fix `$fromAI()` expressions and field format (`queryParameters.parameters`)
- [x] Fix AI agent hallucination - dynamic sessionId instead of static
- [x] Fix Awtrix JSON parse error - switched to key-value body parameters
- [x] Update `doc/api_endpoints.md` - removed old diagram, updated workflow description

### influx_queries.py Fixes (committed)
- [x] Fix `_parse_datetime` end_of_day parameter for date-only strings

### Grafana Dashboard: energy_overview.json (UNCOMMITTED)
- [x] Create dashboard with InfluxQL (not Flux) queries
- [x] Fix datasource UID to `ae6t72jta5gcge`
- [x] Fix INTEGRAL calculation with GROUP BY "device"
- [x] Fix stat panels (Verbrauch/Kosten Heute) - Grafana `reduce` transformation to sum devices
- [x] Fix legend names - `$tag_device` for grouped, `$device` for single-device
- [x] Fix Top-Verbraucher pie chart - changed MEAN(power) to INTEGRAL for real kWh
- [x] Fix liveNow flicker - set to false, refresh 30s -> 1m
- [x] Fix timeFrom overrides for 7d/30d panels
- [x] Fix Solar vs. Verbrauch panels - INTEGRAL(kWh) with stacked bars instead of wrong MEAN
- [ ] User validation: stat panel sum (reduce transformation)
- [ ] User validation: Solar vs. Verbrauch stacked bars
- [ ] User validation: Top-Verbraucher pie chart in kWh

### Grafana Dashboard: appliance_events.json (UNCOMMITTED)
- [x] Rewrite from Flux to InfluxQL
- [x] Set datasource UID to `be6t2vuz2qvi8f`
- [x] 8 stat panels (Espressos, TV, Airfryer, Hairdryer, E-Bike, Wash, Dry, Total)
- [x] Event timeline, pie chart, energy per event, avg duration, last 50 events table
- [ ] User validation after import

## Progress Log
### 2026-03-06 (previous session)
- Fixed n8n workflow tool nodes, sessionId, Awtrix body
- Fixed influx_queries.py date parsing
- Updated api_endpoints.md
- Created initial Grafana dashboards (Flux - broken)

### 2026-03-08 (previous session)
- Rewrote energy_overview.json from Flux to InfluxQL
- Fixed INTEGRAL calculations, legends, stat panel transformations
- Rewrote appliance_events.json entirely to InfluxQL

### 2026-03-09
- Fixed Top-Verbraucher pie chart: MEAN(power) -> INTEGRAL for real kWh values
- Fixed liveNow flicker: disabled liveNow, refresh 30s -> 1m
- Added timeFrom overrides (7d/30d) to panels with fixed time ranges
- Fixed Solar vs. Verbrauch panels: INTEGRAL(kWh) with stacked device bars + non-stacked Solar overlay

## Key Decisions
- InfluxQL (not Flux) required - user's Grafana datasource configured for InfluxQL
- InfluxDB 2.x InfluxQL compatibility does NOT support subqueries
- Grafana `reduce` transformation used to sum per-device INTEGRAL values for stat panels
- Stacked bars approach for "Verbrauch vs Solar" since SUM of MEAN not possible in InfluxQL

## Open Questions
- Do the stat panel reduce transformations produce correct totals? (needs user validation)
- Are the stacked bar charts readable enough for the Solar vs Verbrauch comparison?
- Does the appliance_events dashboard show data correctly after InfluxQL rewrite?

## Files Modified
- `grafana/dashboards/energy_overview.json` - full InfluxQL dashboard (UNCOMMITTED)
- `grafana/dashboards/appliance_events.json` - full InfluxQL rewrite (UNCOMMITTED)
- `n8n_workflows/2_ai_energy_analysis.json` - tool nodes, sessionId, Awtrix (committed)
- `influx_queries.py` - end_of_day date parsing fix (committed)
- `doc/api_endpoints.md` - removed old diagram (committed)

## Agent Outputs Referenced
- None
