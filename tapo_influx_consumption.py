import asyncio
import os

from tapo import ApiClient
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


async def fetch_and_write_data():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    solar_ip_address = os.getenv("SOLAR_IP_ADDRESS")
    washing_machine_ip_address = os.getenv("WASCHING_MACHINE_IP_ADDRESS")
    washing_dryer_ip_address = os.getenv("WASCHING_DRYER_IP_ADDRESS")
    cooler_ip_address = os.getenv("COOLER_IP_ADDRESS")
    living_room_window_ip_address = os.getenv("LIVING_ROOM_WINDOW_IP_ADDRESS")
    kitchen_ip_address = os.getenv("KITCHEN_IP_ADDRESS")
    bedroom_ip_address = os.getenv("BEDROOM_IP_ADDRESS")
    television_ip_address = os.getenv("TELEVISION_IP_ADDRESS")
    office_ip_address = os.getenv("OFFICE_IP_ADDRESS")
    hwr_sauger_fahrradcharger_ip_address = os.getenv("HWR_CHARGER_IP_ADDRESS")
    kaffe_bar_ip_address = os.getenv("KAFFE_BAR_IP_ADDRESS")

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
        'office': office_ip_address,
        'hwr_charger': hwr_sauger_fahrradcharger_ip_address,
        'kaffe_bar': kaffe_bar_ip_address,
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
            try:
                device = await client.p110(ip)
                power_data = await device.get_current_power()
                # print(f"Current power {device_name}: {power_data.current_power}")
                
                point = Point("power_consumption") \
                    .tag("device", device_name) \
                    .field("power", power_data.current_power)
                
                write_api.write(bucket=influx_bucket, org="None", record=point)
            except Exception as e:
                print(f"Failed to get power for device {device_name}: {e}")


async def main():
    while True:
        await fetch_and_write_data()
        # Wait for 30 seconds before the next run
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())