import httpx
from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timedelta
from tapo import EnergyDataInterval


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


async def get_energy_data_daily(device):
    # return await device.get_energy_data(
    #     EnergyDataInterval.Daily,
    #     datetime(datetime.today().year, get_quarter_start_month(datetime.today()), 1),
    # )
    return await device.get_energy_data(
        EnergyDataInterval.Daily,
        datetime(datetime.today().year, 1, 1),
    )


def get_date_df_from_dict(data_dict):

    # Calculating start date from end_timestamp and data length
    # convert local_time in format '2024-03-21T10:08:34' to datetime object
    local_time = datetime.strptime(data_dict['local_time'], '%Y-%m-%dT%H:%M:%S')
    # create datetime-object named start_date for date 2024-01-01
    start_date = datetime(local_time.year, 1, 1)

    # end_date = local_time
    # interval_days = data_dict['interval'] // 1440  # Assuming interval is in minutes
    # end_date = start_date + timedelta(days=(len(data_dict['data']) - 1) * interval_days)

    # Generating date range
    dates = [start_date + timedelta(days=i) for i in range(len(data_dict['data']))]

    # Creating DataFrame
    df = pd.DataFrame({
        'Date': dates,
        'Value': data_dict['data']
    })

    # Formatting Date column
    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
    return df
