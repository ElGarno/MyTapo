# Context Session 04 - Add Devices & Deployment Mechanics

## Project Goal
Add two new Tapo P110 plugs to monitoring and document how device config and
deployment actually work (dynamic reload, named volume, Portainer/registry flow).

## Current Status
- **Phase**: completed
- **Last Updated**: 2026-07-17
- **Blockers**: None

## Tasks
- [x] Confirmed KLAP session fix (Session 03) is stable in production (running weeks)
- [x] Added 2 new devices to `config/devices.json` (repo = image source of truth)
- [x] Provided `docker exec` commands to inject devices into the live container
- [x] Documented deployment mechanics (Portainer, registry images, named volume)

## New Devices Added — WORKING
| Key | IP | emoji_id | Notes |
|-----|-----|----------|-------|
| `living_room_pillar_outdoor` | 192.168.178.128 | 9848 | Multi-outlet (mini fridge + occasional laptop charger); P110 measures TOTAL only |
| `outdoor_outlet` | 192.168.178.129 | 67248 | Outdoor socket |

Both live and enabled; `Flushed 16 data points` confirms all 16 devices polled,
`outdoor_outlet` appears in the Awtrix carousel.

## Note: initial 403 was TRANSIENT, not a firmware block
- The 2 new P110 run firmware **1.4.6** (the 14 others run **1.4.0**).
- Right after adding, both showed `Handshake1 error: 403 Forbidden` /
  `Tapo(InvalidResponse)`. Initial (wrong) hypothesis was a hard firmware-1.4.6
  incompatibility with the tapo lib (issue #577).
- Reality: it just needed a bit longer than the ~10s we waited — the fresh device
  needed a couple of re-auth cycles before a working KLAP session established.
  After that, both poll fine on firmware 1.4.6 with the pinned `tapo==0.8.0`.
- Takeaway for next time: after adding a device, if it 403s, give it a few minutes
  / a few re-auth cycles before concluding it's a firmware/library problem. Do NOT
  disable auto-updates or treat 1.4.6 as unsupported based on the initial 403.

## Key Learnings (Deployment Mechanics)

### Dynamic device config DOES work without restart
- `tapo_influx_consumption_dynamic.py` uses a `watchdog` file watcher on `config/`
  (lines ~67-71). On `devices.json` change → `load_config()` reloads.
- Main loop calls `device_manager.get_devices()` every cycle (~15s), so new/changed
  devices are picked up on the next poll. No container restart, no rebuild.
- Carousel iterates ALL devices from `get_devices()` sorted by power. Missing
  `emoji_id` → falls back to a colored circle icon (green/yellow/orange/red by watts).
  So a device appears immediately even without an icon.

### Why it "felt" like dynamic wasn't possible
- Config is a NAMED Docker volume (`config:/usr/src/app/config`), NOT a host bind
  mount. So `devices.json` lives inside the volume, not on the Synology filesystem —
  not obvious how to edit → people just rebuilt.
- To edit live: `docker exec` into the container and patch `config/devices.json`
  (watcher reloads automatically). Container name: `mytapo-awtrix-influx_consumption-1`.

### Deployment reality (IMPORTANT)
- Running stack uses PREBUILT REGISTRY images: `faffi86/mytapo-*:latest`
  (influx_consumption, event_detector, washing, dryer, solar, consumption_reporter,
  report_api). NOT local builds. Stack name: `mytapo-awtrix`.
- User deploys via Portainer: DELETE stack, then rebuild. This appears to recreate the
  `config` named volume fresh → seeded from the image's baked-in `devices.json`.
  That's why repo changes have "always worked" on rebuild.
- Named-volume gotcha: a rebuild only re-seeds `devices.json` if the volume is fresh.
  If the volume persists (not deleted), the OLD device list masks the image version.
- Measurement DATA goes to external InfluxDB (192.168.178.114) — no local data volume;
  the `config` volume only holds the device roster (tiny).
- Persisting new devices for real = bake into repo `config/devices.json` → build image
  → push to `faffi86/mytapo-influx_consumption:latest` → re-pull on Synology.

### `manage_devices.py` limitation
- `add` writes only `ip`/`enabled`/`description` — NOT `emoji_id` or `grafana_group`.
  Set those by patching the JSON directly.

## Files Modified
- `config/devices.json` - added `living_room_pillar_outdoor`, `outdoor_outlet`

## Open Questions
- Confirm on Synology whether Portainer stack-delete actually removes the `config`
  volume (`docker volume ls | grep config` before/after) — determines if rebuild is
  the true source of truth or if the volume can mask new config.

## Agent Outputs Referenced
- None
