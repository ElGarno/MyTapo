import asyncio
import os
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt

from tapo import ApiClient, EnergyDataInterval
from dotenv import load_dotenv


async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    solar_ip_address = "192.168.178.61"
    wasching_machine_ip_address = "192.168.178.52"

    client = ApiClient(tapo_username, tapo_password)
    device_solar = await client.p110(solar_ip_address)
    device_wasching_machine = await client.p110(wasching_machine_ip_address)

    device_info = await device_solar.get_device_info()
    print(f"Device info: {device_info.to_dict()}")
    dict_energy_data_daily = (await get_energy_data_daily(device_solar)).to_dict()
    print(f"Energy data (daily): {dict_energy_data_daily}")
    df_energy_consumption = get_date_df_from_dict(dict_energy_data_daily)
    df_energy_consumption.plot(kind='bar', x='Date', y='Value', title='Energy consumption (daily)')
    plt.savefig('energy_consumption_daily.png')

    cur_power_solar = await device_solar.get_current_power()
    print(f"Current power solar: {cur_power_solar.to_dict()}")

    cur_power_wasching_machine = await device_wasching_machine.get_current_power()
    print(f"Current power wasching machine: {cur_power_wasching_machine.to_dict()}")


def get_quarter_start_month(today: datetime) -> int:
    return 3 * ((today.month - 1) // 3) + 1


async def get_energy_data_daily(device):
    return await device.get_energy_data(
        EnergyDataInterval.Daily,
        datetime(datetime.today().year, get_quarter_start_month(datetime.today()), 1),
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


if __name__ == "__main__":
    asyncio.run(main())