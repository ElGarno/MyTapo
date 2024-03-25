import httpx
from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timedelta


def send_pushover_notification(user, message):
    load_dotenv()
    pushover_api_token = os.getenv("PUSHOVER_TAPO_API_TOKEN")

    response = httpx.post("https://api.pushover.net/1/messages.json", data={
        "token": pushover_api_token,
        "user": user,
        "message": message,
    })
    print(response.text)


async def monitor_power_and_notify(device, user, threshold_high=50, threshold_low=10, duration_minutes=5, message=""):
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
                send_pushover_notification(user=user, message=message)
                power_exceeded = False  # Reset condition
                low_power_start_time = None  # Reset timer
        else:
            low_power_start_time = None  # Reset if current power is not low

        await asyncio.sleep(60)  # Check every minute
