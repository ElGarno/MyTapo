import asyncio
import os
from datetime import datetime, timedelta

from tapo import ApiClient
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    solar_ip_address = "192.168.178.61"
    washing_machine_ip_address = "192.168.178.52"
    washing_dryer_ip_address = "192.168.178.54"
    cooler_ip_address = "192.168.178.86"
    living_room_window_ip_address = "192.168.178.75"
    kitchen_ip_address = "192.168.178.74"
    bedroom_ip_address = "192.168.178.60"
    television_ip_address = "192.168.178.58"
    office_ip_address = "192.168.178.55"

    client = ApiClient(tapo_username, tapo_password)
    # Define devices
    devices = {
        'solar': solar_ip_address,
        'washing_machine': washing_machine_ip_address,
        'washing_dryer': washing_dryer_ip_address,
        'cooler': cooler_ip_address,
        'living_room_window': living_room_window_ip_address,
        'kitchen': kitchen_ip_address,
        'bedroom': bedroom_ip_address,
        'television': television_ip_address,
        'office': office_ip_address
    }

    # Create InfluxDB client

    influx_url = "http://192.168.178.114:8088"
    influx_token = os.environ.get("INFLUXDB_TOKEN")
    influx_org = "None"
    influx_bucket = "power_consumption"

    with InfluxDBClient(url=influx_url, token=influx_token, org=influx_org) as influx_client:
        write_api = influx_client.write_api(write_options=SYNCHRONOUS)

        # Get power for each device and write to InfluxDB
        for device_name, ip in devices.items():
            device = await client.p110(ip)
            power_data = await device.get_current_power()
            print(f"Current power {device_name}: {power_data.current_power}")
            
            point = Point("power_consumption") \
                .tag("device", device_name) \
                .field("power", power_data.current_power)
            
            write_api.write(bucket=influx_bucket, org="None", record=point)


if __name__ == "__main__":
    asyncio.run(main())