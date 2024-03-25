import asyncio
import os
from datetime import datetime, timedelta
from tapo import ApiClient, EnergyDataInterval
from dotenv import load_dotenv

from utils import send_pushover_notification


async def monitor_power_and_notify(device, user, threshold_high=50, threshold_low=10, duration_minutes=5):
    power_exceeded = False
    low_power_start_time = None
    sensor_name = 'current_power'

    while True:
        current_power = (await device.get_current_power()).to_dict()
        print(f"Current power: {current_power[sensor_name]}W")  # For debugging

        if current_power[sensor_name] > threshold_high:
            power_exceeded = True
            low_power_start_time = None  # Reset since power is high again

        if power_exceeded and current_power[sensor_name] < threshold_low:
            if low_power_start_time is None:
                low_power_start_time = datetime.now()
            elif datetime.now() - low_power_start_time > timedelta(minutes=duration_minutes):
                send_pushover_notification(user=user, message="Die Wäsche ist fertig, Tapsi! 🧺🐶")
                power_exceeded = False  # Reset condition
                low_power_start_time = None  # Reset timer
        else:
            low_power_start_time = None  # Reset if current power is not low

        await asyncio.sleep(60)  # Check every minute


async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    pushover_user_key = os.getenv("PUSHOVER_USER_KEY")
    pushover_user_group = os.getenv("PUSHOVER_USER_GROUP_WOERIS")
    wasching_machine_ip_address = os.getenv("WASCHING_MACHINE_IP_ADDRESS")

    client = ApiClient(tapo_username, tapo_password)
    device_wasching_machine = await client.p110(wasching_machine_ip_address)
    # current_power = (await device_wasching_machine.get_current_power()).to_dict()
    await monitor_power_and_notify(device_wasching_machine, pushover_user_group)
    # send_pushover_notification(f"Current power: {current_power['current_power']}W")

if __name__ == "__main__":
    asyncio.run(main())
