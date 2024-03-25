import asyncio
import os
from datetime import datetime
from tapo import ApiClient
from dotenv import load_dotenv
from utils import get_energy_data_daily, get_date_df_from_dict, send_pushover_notification


async def monitor_generated_solar_energy_and_notify(device_solar, user):
    while True:
        dict_energy_data_daily = (await get_energy_data_daily(device_solar)).to_dict()
        df_energy_consumption = get_date_df_from_dict(dict_energy_data_daily)
        df_energy_consumption.set_index('Date', inplace=True)
        solar_energy_generated_today = df_energy_consumption.loc[str(datetime.today().date())]['Value']
        max_solar_energy = df_energy_consumption['Value'].max()
        message = f"The energy consumed today has been {solar_energy_generated_today / 1000:.4g} kWh which is {solar_energy_generated_today / max_solar_energy:.1%} of the maximum energy generated this year."
        # send notification every day at 11pm
        print(message)
        if (datetime.now().hour == 23) and (datetime.now().minute == 0):
            send_pushover_notification(user, message)
        await asyncio.sleep(60)



async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    pushover_user_key = os.getenv("PUSHOVER_USER_KEY")
    pushover_user_group = os.getenv("PUSHOVER_USER_GROUP_WOERIS")
    solar_ip_address = os.getenv("SOLAR_IP_ADDRESS")

    client = ApiClient(tapo_username, tapo_password)
    device_solar = await client.p110(solar_ip_address)
    await monitor_generated_solar_energy_and_notify(device_solar, pushover_user_key)

if __name__ == "__main__":
    asyncio.run(main())