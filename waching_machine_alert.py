import httpx
import asyncio
import os
from datetime import datetime, timedelta
from tapo import ApiClient, EnergyDataInterval
from dotenv import load_dotenv


async def check_power_and_notify(device):
    current_power = await device.get_current_power()
    print(f"Current power: {current_power.to_dict()}")

    power_threshold = 1000  # Define your threshold here
    if current_power['power'] > power_threshold:
        message = f"Power exceeded threshold: {current_power['power']}W"
        send_pushover_notification(message)


def send_pushover_notification(message):
    load_dotenv()
    pushover_user_key = os.getenv("PUSHOVER_USER_KEY")
    pushover_api_token = os.getenv("PUSHOVER_TAPO_API_TOKEN")

    response = httpx.post("https://api.pushover.net/1/messages.json", data={
        "token": pushover_api_token,
        "user": pushover_user_key,
        "message": message,
    })
    print(response.text)


async def monitor_power_and_notify(device, threshold_high=50, threshold_low=10, duration_minutes=5):
    power_exceeded = False
    low_power_start_time = None

    while True:
        current_power = (await device.get_current_power()).to_dict()
        print(f"Current power: {current_power['current_power']}W")  # For debugging

        if current_power['power'] > threshold_high:
            power_exceeded = True
            low_power_start_time = None  # Reset since power is high again

        if power_exceeded and current_power['power'] < threshold_low:
            if low_power_start_time is None:
                low_power_start_time = datetime.now()
            elif datetime.now() - low_power_start_time > timedelta(minutes=duration_minutes):
                send_pushover_notification("Die Wäsche ist fertig, Tapsi! 🧺🐶")
                power_exceeded = False  # Reset condition
                low_power_start_time = None  # Reset timer
        else:
            low_power_start_time = None  # Reset if current power is not low

        await asyncio.sleep(60)  # Check every minute


async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    wasching_machine_ip_address = os.getenv("WASCHING_MACHINE_IP_ADDRESS")

    client = ApiClient(tapo_username, tapo_password)
    device_wasching_machine = await client.p110(wasching_machine_ip_address)
    # current_power = (await device_wasching_machine.get_current_power()).to_dict()
    await monitor_power_and_notify(device_wasching_machine)
    # send_pushover_notification(f"Current power: {current_power['current_power']}W")

if __name__ == "__main__":
    asyncio.run(main())
