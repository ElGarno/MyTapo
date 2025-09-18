# MyTapo

MyTapo is a Python-based project aimed at enabling users to monitor energy consumption using smart plugs. The application interfaces with Tapo smart plugs to retrieve and analyze energy data, providing insights into usage patterns and potential savings.

## Features
- **Energy Monitoring**: Track real-time energy consumption of connected devices.
- **Data Visualization**: View energy usage trends over time through graphs and charts.
- **Alerts & Notifications**: Set up alerts for abnormal energy usage or costs.
- **Multi-Device Support**: Monitor multiple Tapo devices from a single interface.

## Requirements
- Python 3.x
- Required Python Packages: `requests`, `matplotlib`, etc.

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/ElGarno/MyTapo.git
   cd MyTapo
   ```
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

## Usage
1. Configure your Tapo credentials in the configuration file.
2. Run the main script:
   ```bash
   python main.py
   ```
3. Follow the on-screen instructions to monitor your energy consumption.

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

## Contributing
Contributions are welcome! Please feel free to open issues or submit pull requests.

## License
This project is licensed under the MIT License.