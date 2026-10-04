# Context Session 05 - Repository Cleanup

## Project Goal
Remove obsolete docker-compose files, legacy scripts and old data exports so the
repo root only contains what production and development actually use.

## Current Status
- **Phase**: completed
- **Last Updated**: 2026-10-04 20:50
- **Blockers**: None

## Tasks
- [x] Audit docker-compose files (which are still used)
- [x] Remove `docker-compose.{local,portainer,synology}.yml` and `docker-compose.yml.backup`
- [x] Remove unreferenced/legacy files (see Files Modified)
- [x] Update CLAUDE.md (uv instead of Poetry, pytest, two-compose-file setup)
- [x] Verify tests still pass (`uv run pytest` -> 22 passed)
- [x] Commit + push (`5ef7fb5`)
- [ ] Check whether `notebook`, `ipykernel`, `ipython`, `pyarrow`, `fastparquet` can be dropped from `pyproject.toml` (likely only used by the removed notebook/Parquet exports)
- [ ] README.md Docker section: `docker-compose up --build` does not build with the prod file (image-based), and service name `solar` should be `solar_energy_monitor`

## Decisions
- Keep `docker-compose.yml` (prod, Docker Hub images `faffi86/mytapo-*`)
- Keep `docker-compose.dev.yml` (local build + `backfill_events` under profile `backfill`)
- Keep `awtrix_energy_monitor.py` and `solarbank_schedule_optimizer.py` (+ png); not in any Dockerfile but possibly run manually

## Progress Log
### 2026-10-04
- Completed: compose file audit, removal of 17 obsolete files, CLAUDE.md update, commit + push
- Decisions made: see Decisions
- Next: pyproject dependency cleanup, README Docker section fix

## Files Modified
- `CLAUDE.md` - uv, pytest, compose file overview, dynamic collector as data layer
- Removed: `docker-compose.local.yml`, `docker-compose.portainer.yml`, `docker-compose.synology.yml`, `docker-compose.yml.backup`
- Removed: `tapo_influx_consumption.py`, `diagnose_protocol.py`, `test_new_devices.py`, `tapo_test.py`, `tests.ipynb`
- Removed: `power_consumption_export_{20250321,20250424}.{csv,parquet}`, `energy_consumption_daily.png`
- Removed: `poetry.lock`, `cltv_import_settings.json`, `__pycache__/utils.cpython-313.pyc`

## Agent Outputs Referenced
- None

## Open Questions
- Is `awtrix_energy_monitor.py` still run manually, or can it go too?
- Should the removed CSV/Parquet exports be purged from git history (`.git` is 34 MB)?
