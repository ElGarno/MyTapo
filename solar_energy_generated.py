import asyncio
import os
from datetime import datetime
from tapo import ApiClient
from dotenv import load_dotenv
from utils import get_df_energy_consumption, compute_mean_energy_consumption, compute_costs, send_pushover_notification_new, get_awtrix_client


async def monitor_generated_solar_energy_and_notify(device_solar, user, enable_awtrix=True):
    awtrix_client = get_awtrix_client() if enable_awtrix else None
    last_solar_report = None
    last_current_power_display = None
    last_energy_data_fetch = None
    last_daily_stats_log = None
    last_pushover_sent = None
    cached_energy_data = None
    
    while True:
        try:
            current_time = datetime.now()
            
            # Fetch energy data only every 10 minutes to reduce API calls and logging spam
            if (last_energy_data_fetch is None or 
                (current_time - last_energy_data_fetch).total_seconds() >= 600):  # 10 minutes
                
                try:
                    cached_energy_data = await get_df_energy_consumption(device_solar)
                    last_energy_data_fetch = current_time
                except Exception as e:
                    print(f"Error fetching energy data: {e}")
                    if cached_energy_data is None:
                        await asyncio.sleep(60)
                        continue
            
            # Use cached data if available
            if cached_energy_data is None:
                await asyncio.sleep(60)
                continue
                
            df_energy_consumption = cached_energy_data
            today_str = str(datetime.today().date())
            
            # Check if today's data exists in the dataframe
            if today_str not in df_energy_consumption.index:
                print(f"No energy data available for today ({today_str})")
                await asyncio.sleep(60)
                continue
                
            solar_energy_generated_today = df_energy_consumption.loc[today_str]['Value']
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
            
            # Log daily stats only every 30 minutes to reduce log spam
            if (last_daily_stats_log is None or 
                (current_time - last_daily_stats_log).total_seconds() >= 1800):  # 30 minutes
                print(f"[{current_time.strftime('%H:%M')}] {message}")
                last_daily_stats_log = current_time
            
            # Get current solar power generation
            try:
                current_solar_power = await device_solar.get_current_power()
                current_power_w = current_solar_power.current_power
            except Exception as e:
                print(f"Error getting current solar power: {e}")
                current_power_w = 0
            
            # Display current solar power every 10 minutes during daylight hours (6-19)
            if (enable_awtrix and awtrix_client and 
                6 <= current_time.hour <= 19 and
                (last_current_power_display is None or 
                 (current_time - last_current_power_display).total_seconds() >= 600)):  # 10 minutes
                
                try:
                    from awtrix_client import AwtrixMessage
                    
                    # Determine icon and color based on power generation
                    if current_power_w > 1000:
                        icon = "2600"    # Sun
                        color = "#FFD700"  # Gold
                    elif current_power_w > 500:
                        icon = "9728"    # Partly sunny
                        color = "#FFA500"  # Orange
                    elif current_power_w > 100:
                        icon = "9729"    # Cloudy
                        color = "#87CEEB"  # Sky blue
                    else:
                        icon = "9729"    # Cloud
                        color = "#696969"  # Gray
                    
                    power_message = AwtrixMessage(
                        text=f"Solar: {current_power_w:.0f}W",
                        icon=icon,
                        color=color,
                        duration=8
                    )
                    
                    awtrix_client.send_notification(power_message)
                    print(f"Sent current solar power: {current_power_w}W")
                    last_current_power_display = current_time
                    
                except Exception as e:
                    print(f"Error sending current power display: {e}")
            
            # Solar energy report every 2 hours during daylight (7-19)
            if (enable_awtrix and awtrix_client and 
                7 <= current_time.hour <= 19 and
                (last_solar_report is None or 
                 (current_time - last_solar_report).total_seconds() >= 7200)):  # 2 hours
                
                try:
                    awtrix_client.send_solar_report(
                        solar_energy_generated_today / 1000, 
                        saved_costs_today
                    )
                    print(f"Sent solar report: {solar_energy_generated_today/1000:.2f} kWh, €{saved_costs_today:.2f}")
                    last_solar_report = current_time
                except Exception as e:
                    print(f"Error sending solar report: {e}")
            
            # Daily evening notification between 9-10pm (more flexible timing)
            if (20 <= current_time.hour <= 21 and 
                (last_pushover_sent is None or 
                 last_pushover_sent.date() != current_time.date())):
                
                try:
                    send_pushover_notification_new(user, message)
                    print(f"Sent daily Pushover notification at {current_time.strftime('%H:%M')}")
                    last_pushover_sent = current_time
                    
                    if enable_awtrix and awtrix_client:
                        try:
                            awtrix_client.send_solar_report(
                                solar_energy_generated_today / 1000, 
                                saved_costs_today
                            )
                        except Exception as e:
                            print(f"Error sending evening solar report: {e}")
                except Exception as e:
                    print(f"Error sending Pushover notification: {e}")
        
        except Exception as e:
            print(f"Error in solar monitoring loop: {e}")
        
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
