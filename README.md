# MyTapo

MyTapo is a Python-based project aimed at enabling users to monitor energy consumption using smart plugs. The application interfaces with Tapo smart plugs to retrieve and analyze energy data, providing insights into usage patterns and potential savings.

## Features
- **Energy Monitoring**: Track real-time energy consumption of connected devices.
- **Data Visualization**: View energy usage trends over time through graphs and charts.
- **Alerts & Notifications**: Set up alerts for abnormal energy usage or costs.
- **Multi-Device Support**: Monitor multiple Tapo devices from a single interface.
- **Appliance Event Detection**: Automatically detect and track appliance usage events (espresso, TV sessions, wash cycles, etc.) with analytics and AWTRIX display integration. See [EVENT_DETECTION.md](EVENT_DETECTION.md) for details.

## Requirements
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) - Fast Python package installer and resolver
- InfluxDB instance (for time-series data storage)
- Tapo P110 smart plugs

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/ElGarno/MyTapo.git
   cd MyTapo
   ```

2. Install uv (if not already installed):
   ```bash
   # On macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # On Windows
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

3. Install project dependencies:
   ```bash
   uv sync
   ```

4. Configure your environment:
   - Copy `.env.template` to `.env`
   - Fill in your Tapo credentials, InfluxDB connection details, and Pushover API keys

## Usage

### Running Monitoring Services

```bash
# Run the dynamic data collection service (recommended)
uv run python tapo_influx_consumption_dynamic.py

# Run individual monitoring services
uv run python washing_machine_alert.py
uv run python washing_dryer_alert.py
uv run python solar_energy_generated.py
```

### Device Management

```bash
# List all configured devices
uv run python manage_devices.py list

# Add a new device
uv run python manage_devices.py add device_name 192.168.178.100 "Device description"

# Enable/disable a device
uv run python manage_devices.py enable device_name
uv run python manage_devices.py disable device_name
```

### Event Detection Service

```bash
# Run the event detector (detects appliance usage events)
uv run python event_detector.py

# Generate analytics reports manually
uv run python analytics_generator.py
```

For full documentation on event detection, AWTRIX integration, and Grafana dashboards, see [EVENT_DETECTION.md](EVENT_DETECTION.md).

### Docker Deployment

```bash
# Build and run all services
docker-compose up --build

# Run specific services
docker-compose up influx_consumption
docker-compose up solar
docker-compose up event_detector
```

## Troubleshooting

### Session Timeout Issues
The Tapo API sessions expire after approximately 3-4 hours of continuous use, which can cause the following errors:
- `Tapo(SessionTimeout)` - Session has expired
- `403 Forbidden` errors from the KLAP protocol
- `No objects to concatenate` - When no data can be fetched due to authentication failure

**Solution implemented:**
- **Automatic session refresh**: The solar monitoring service now refreshes device connections every 2 hours proactively
- **Reactive reconnection**: When authentication errors are detected, the service automatically reconnects
- **Graceful error handling**: Empty data responses are handled without crashing the service

The monitoring services will now automatically recover from session timeouts and continue running indefinitely without manual intervention.

## Documentation

- [EVENT_DETECTION.md](EVENT_DETECTION.md) - Appliance event detection, AWTRIX integration, and Grafana dashboards
- [GRAFANA_OFFICE_QUERY.md](GRAFANA_OFFICE_QUERY.md) - Flux queries for combining office devices in Grafana

## Contributing
Contributions are welcome! Please feel free to open issues or submit pull requests.

## License
This project is licensed under the MIT License.