import asyncio
import os
from datetime import datetime
from tapo import ApiClient
from dotenv import load_dotenv
from utils import get_df_energy_consumption, compute_mean_energy_consumption, compute_costs, send_pushover_notification_new, get_awtrix_client


async def monitor_generated_solar_energy_and_notify(device_solar, user, enable_awtrix=True):
    awtrix_client = get_awtrix_client() if enable_awtrix else None
    last_hourly_notification = None
    
    while True:
        df_energy_consumption = await get_df_energy_consumption(device_solar)
        solar_energy_generated_today = df_energy_consumption.loc[str(datetime.today().date())]['Value']
        max_solar_energy = df_energy_consumption['Value'].max()
        mean_solar_energy = compute_mean_energy_consumption(df_energy_consumption)
        saved_costs_today = compute_costs(solar_energy_generated_today / 1000)
        # sum up generated energy for the year
        saved_energy_this_year = df_energy_consumption['Value'].sum()
        saved_costs_year = compute_costs(saved_energy_this_year / 1000)

        message = (f"The energy consumed today has been {solar_energy_generated_today / 1000:.4g} kWh "
                   f"which is {solar_energy_generated_today / max_solar_energy:.1%} of the maximum energy generated "
                   f"this year ({max_solar_energy / 1000:.4g} kWh)."
                   f"You saved {saved_costs_today:.2f} € today (assuming 28Cent/kWh) and {saved_costs_year:.2f} € this year. "
                   f"The mean energy consumption is {mean_solar_energy:.2f} kWh.")
        
        print(message)
        
        current_time = datetime.now()
        
        # Hourly Awtrix notifications (during daylight hours 8-20)
        if (enable_awtrix and awtrix_client and 
            8 <= current_time.hour <= 20 and 
            current_time.minute == 0 and
            (last_hourly_notification is None or 
             (current_time - last_hourly_notification).seconds > 3300)):  # More than 55 minutes
            
            awtrix_client.send_solar_report(
                solar_energy_generated_today / 1000, 
                saved_costs_today
            )
            last_hourly_notification = current_time
        
        # Daily evening notification at 9pm
        if (current_time.hour == 21) and (current_time.minute == 0):
            send_pushover_notification_new(user, message)
            if enable_awtrix and awtrix_client:
                awtrix_client.send_solar_report(
                    solar_energy_generated_today / 1000, 
                    saved_costs_today
                )
        
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
    await monitor_generated_solar_energy_and_notify(device_solar, pushover_user_group)

if __name__ == "__main__":
    asyncio.run(main())
