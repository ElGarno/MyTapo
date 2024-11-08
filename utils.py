from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timedelta
from tapo.requests import EnergyDataInterval
import pandas as pd
import requests


def send_pushover_notification(user, message):
    load_dotenv()
    pushover_api_token = os.getenv("PUSHOVER_TAPO_API_TOKEN")
    r = requests.post("https://api.pushover.net/1/messages.json", data = {
        "token": pushover_api_token,
        "user": user,
        "message": message
    },)
    # files = {
    #     "attachment": ("image.jpg", open("your_image.jpg", "rb"), "image/jpeg")
    # })
    print(r.text)


# def send_pushover_notification_new(user, message):
#     load_dotenv()
#     conn = http.client.HTTPSConnection("api.pushover.net:443")
#     pushover_api_token = os.getenv("PUSHOVER_TAPO_API_TOKEN")
#     conn.request("POST", "/1/messages.json",
#                  urllib.parse.urlencode({
#                      "token": pushover_api_token,
#                      "user": user,
#                      "message": message,
#                  }), {"Content-type": "application/x-www-form-urlencoded"})
#     conn.getresponse()


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


async def get_energy_data_daily(device, startmonth):
    return await device.get_energy_data(
        EnergyDataInterval.Daily,
        datetime(datetime.today().year, startmonth, 1),
        datetime.today()
    )


def get_date_df_from_dict(data_dict, startmonth):

    # Calculating start date from end_timestamp and data length
    # convert local_time in format '2024-03-21T10:08:34' to datetime object
    local_time = datetime.strptime(data_dict['local_time'], '%Y-%m-%dT%H:%M:%S')
    # create datetime-object named start_date for date 2024-01-01
    start_date = datetime(local_time.year, startmonth, 1)

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


def compute_mean_energy_consumption(df_energy_consumption):
    # drop zeros
    df_energy_consumption = df_energy_consumption[df_energy_consumption['Value'] > 0]
    mean_energy_consumption = df_energy_consumption['Value'].mean()
    return mean_energy_consumption


def compute_costs(saved_kwh, cost_per_kwh=0.28):
    savings = saved_kwh * cost_per_kwh
    return savings


async def get_df_energy_consumption(device_solar):
    cur_quarter = (datetime.today().month - 1) // 3 + 1
    list_dict_energy_data_daily = []
    for i_quarter in range(1, cur_quarter + 1):
        quarter_start_month = 3 * (i_quarter - 1) + 1
        dict_energy_data_daily = (await get_energy_data_daily(device_solar, quarter_start_month)).to_dict()
        list_dict_energy_data_daily.append(dict_energy_data_daily)
    # concat dicts to one
    df_energy_consumption = []
    for i_quarter_m1, dict_energy_data in enumerate(list_dict_energy_data_daily):
        quarter_start_month = 3 * i_quarter_m1 + 1
        df_energy_consumption.append(get_date_df_from_dict(dict_energy_data, quarter_start_month))
    df_energy_consumption = pd.concat(df_energy_consumption)
    # delete dates that are in the future
    df_energy_consumption = df_energy_consumption[df_energy_consumption['Date'] <= datetime.today().strftime('%Y-%m-%d')]
    df_energy_consumption.set_index('Date', inplace=True)
    return df_energy_consumption
