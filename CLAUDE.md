# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MyTapo is a Python-based smart home energy monitoring system that interfaces with Tapo P110 smart plugs to track power consumption across 11 household devices. The system provides real-time monitoring, intelligent alerts, and data export capabilities with InfluxDB integration for time-series storage.

## Development Setup

### Dependencies
- **Python**: 3.13
- **Package Manager**: Poetry (`poetry install` to install dependencies)
- **Key Libraries**: tapo, pandas, matplotlib, influxdb-client, asyncio

### Environment Configuration
- Create `.env` file with required credentials (Tapo accounts, InfluxDB connection, Pushover API keys)
- InfluxDB instance expected at 192.168.178.114:8088

## Common Commands

### Development
```bash
# Install dependencies
poetry install

# Run main data collection service (legacy)
python tapo_influx_consumption.py

# Run dynamic data collection service (recommended)
python tapo_influx_consumption_dynamic.py

# Manage devices dynamically
python manage_devices.py list
python manage_devices.py add new_device 192.168.178.100 "New device description"
python manage_devices.py disable bedroom
python manage_devices.py enable bedroom

# Run individual monitoring services
python waching_machine_alert.py
python waching_dryer_alert.py  
python solar_energy_generated.py

# Interactive testing/development
python tapo_test.py
jupyter notebook tests.ipynb
```

### Docker Deployment
```bash
# Build and run all services
docker-compose up --build

# Individual service builds
docker build -f Dockerfile.influx_consumption .
docker build -f Dockerfile.solar .
docker build -f Dockerfile.washing .
docker build -f Dockerfile.dryer .
```

## Architecture

### Core Components

1. **Data Collection Layer** (`tapo_influx_consumption.py`)
   - Polls 11 Tapo devices every 30 seconds
   - Writes power consumption data to InfluxDB
   - Handles device connectivity and error recovery

2. **Alert System**
   - `waching_machine_alert.py` - Detects washing cycle completion
   - `waching_dryer_alert.py` - Monitors dryer operations
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

No formal test framework is configured. Testing is done via:
- `tapo_test.py` for manual device testing
- `tests.ipynb` Jupyter notebook for interactive development
- Direct execution of individual monitoring scripts

## Deployment

Containerized microservices approach with separate Dockerfiles for each monitoring service. All services orchestrated via Docker Compose for production deployment.