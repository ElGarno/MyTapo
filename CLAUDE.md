# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MyTapo is a Python-based smart home energy monitoring system that interfaces with Tapo P110 smart plugs to track power consumption across 11 household devices. The system provides real-time monitoring, intelligent alerts, and data export capabilities with InfluxDB integration for time-series storage.

## Development Setup

### Dependencies
- **Python**: 3.13
- **Package Manager**: uv (`uv sync` to install dependencies); Docker images install from `requirements.txt`
- **Key Libraries**: tapo, pandas, matplotlib, influxdb-client, asyncio

### Environment Configuration
- Create `.env` file with required credentials (Tapo accounts, InfluxDB connection, Pushover API keys)
- InfluxDB instance expected at 192.168.178.114:8088

## Common Commands

### Development
```bash
# Install dependencies
uv sync

# Run data collection service
python tapo_influx_consumption_dynamic.py

# Manage devices dynamically
python manage_devices.py list
python manage_devices.py add new_device 192.168.178.100 "New device description"
python manage_devices.py disable bedroom
python manage_devices.py enable bedroom

# Run individual monitoring services
python washing_machine_alert.py
python washing_dryer_alert.py
python solar_energy_generated.py

# Run tests
uv run pytest
```

### Docker Deployment
Two compose files:
- `docker-compose.yml` – production, pulls prebuilt `faffi86/mytapo-*` images from Docker Hub
- `docker-compose.dev.yml` – builds all images locally from the `Dockerfile.*` files; also contains the `backfill_events` one-off service (profile `backfill`)

```bash
# Production
docker compose up -d

# Local build
docker compose -f docker-compose.dev.yml up --build

# Backfill events (one-off)
docker compose -f docker-compose.dev.yml --profile backfill run --rm backfill_events
```

## Architecture

### Core Components

1. **Data Collection Layer** (`tapo_influx_consumption_dynamic.py`)
   - Polls 11 Tapo devices every 30 seconds
   - Writes power consumption data to InfluxDB
   - Handles device connectivity and error recovery

2. **Alert System**
   - `washing_machine_alert.py` - Detects washing cycle completion
   - `washing_dryer_alert.py` - Monitors dryer operations
   - `solar_energy_generated.py` - Daily solar generation reports

3. **Utilities** (`utils.py`)
   - Common functions for power monitoring
   - Energy cost calculations (28 cents/kWh)
   - Pushover notification integration
   - Data export (CSV/Parquet) functionality

### Device Network
- 11 monitored devices with static IP addresses (192.168.178.x range)
- Main devices: Solar panels, washing machine, dryer, various room outlets
- All devices are Tapo P110 smart plugs

### Data Flow
- Async polling → InfluxDB storage → Alert processing → Pushover notifications
- 30-second collection intervals for real-time monitoring
- Threshold-based alerting for appliance state changes

## Key Patterns

### Async Operations
All device communication uses async/await patterns for non-blocking I/O operations.

### Error Handling
Device connectivity issues are logged and handled gracefully without stopping the monitoring loop.

### Dynamic Device Configuration
The system supports hot-reloading device configuration without container restart:
- `config/devices.json` - JSON config file with device IPs and settings
- File watcher automatically reloads config when changed  
- `manage_devices.py` - CLI utility for device management
- Devices can be enabled/disabled individually
- Add/remove devices on-the-fly without service interruption

### Static Configuration  
- Environment variables for credentials and API keys
- InfluxDB connection settings via .env file

## Testing

pytest (dev dependency group). Tests live in `tests/`; run with `uv run pytest`.

## Deployment

Containerized microservices approach with separate Dockerfiles for each monitoring service. All services orchestrated via Docker Compose for production deployment.