from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, timedelta
from tapo.requests import EnergyDataInterval
import pandas as pd
# import requests
import http.client, urllib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from awtrix_client import AwtrixClient, AwtrixMessage

# Configure logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# def send_pushover_notification(user, message):
#     load_dotenv()
#     pushover_api_token = os.getenv("PUSHOVER_TAPO_API_TOKEN")
#     r = requests.post("https://api.pushover.net/1/messages.json", data = {
#         "token": pushover_api_token,
#         "user": user,
#         "message": message
#     },)
#     # files = {
#     #     "attachment": ("image.jpg", open("your_image.jpg", "rb"), "image/jpeg")
#     # })
#     print(r.text)


def send_pushover_notification_new(user, message):
    load_dotenv()
    pushover_api_token = os.getenv("PUSHOVER_TAPO_API_TOKEN")
    
    if not pushover_api_token:
        logger.error("PUSHOVER_TAPO_API_TOKEN environment variable not set")
        return False
    
    if not user or not message:
        logger.error(f"Missing required parameters: user={bool(user)}, message={bool(message)}")
        return False
    
    try:
        conn = http.client.HTTPSConnection("api.pushover.net:443")
        conn.request("POST", "/1/messages.json",
                     urllib.parse.urlencode({
                         "token": pushover_api_token,
                         "user": user,
                         "message": message,
                     }), {"Content-type": "application/x-www-form-urlencoded"})
        
        response = conn.getresponse()
        response_data = response.read().decode()
        
        if response.status == 200:
            logger.info(f"Pushover notification sent successfully: {message[:50]}...")
            return True
        else:
            logger.error(f"Pushover API error {response.status}: {response_data}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to send Pushover notification: {e}")
        return False
    finally:
        try:
            conn.close()
        except:
            pass
    

async def monitor_power_and_notify(device, user, threshold_high=50, threshold_low=10, duration_minutes=5, message="", max_retries=3, max_delay=60):
    power_exceeded = False
    low_power_start_time = None
    sensor_name = 'current_power'

    while True:
        retry_count = 0
        while retry_count < max_retries:
            try:
                current_power = (await device.get_current_power()).to_dict()
                logger.info(f"{device_name} current power: {current_power[sensor_name]}W")
                break
            except Exception as e:
                retry_count += 1

                # Check for authentication/session errors - raise to trigger reconnection
                if ("403" in str(e) or "Forbidden" in str(e) or
                    "SessionTimeout" in str(e) or "Response error" in str(e)):
                    logger.error(f"Authentication error detected in monitor_power_and_notify: {e}")
                    raise e  # Re-raise to let calling function handle reconnection

                if retry_count == max_retries:
                    logger.error(f"Failed to get power for {device_name} after {max_retries} attempts: {e}")
                    await asyncio.sleep(max_delay)
                    continue
                await asyncio.sleep(min(2 ** retry_count, max_delay))

        if current_power[sensor_name] > threshold_high:
            power_exceeded = True
            low_power_start_time = None  # Reset since power is high again

        if power_exceeded and current_power[sensor_name] < threshold_low:
            if low_power_start_time is None:
                low_power_start_time = datetime.now()
            elif datetime.now() - low_power_start_time > timedelta(minutes=duration_minutes):
                send_pushover_notification_new(user=user, message=message)
                power_exceeded = False  # Reset condition
                low_power_start_time = None  # Reset timer
        else:
            low_power_start_time = None  # Reset if current power is not low

        await asyncio.sleep(20)  # Check every minute


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


async def get_df_energy_consumption(device_solar, max_retries=3, max_delay=60):
    cur_quarter = (datetime.today().month - 1) // 3 + 1
    list_dict_energy_data_daily = []
    for i_quarter in range(1, cur_quarter + 1):
        quarter_start_month = 3 * (i_quarter - 1) + 1
        retry_count = 0
        while retry_count < max_retries:
            try:
                dict_energy_data_daily = (await get_energy_data_daily(device_solar, quarter_start_month)).to_dict()
                list_dict_energy_data_daily.append(dict_energy_data_daily)
                break
            except Exception as e:
                retry_count += 1
                print(f"Retry {retry_count}/{max_retries} - Error getting energy data: {e}")

                # Check for authentication/session errors - raise to trigger reconnection
                if ("403" in str(e) or "Forbidden" in str(e) or
                    "SessionTimeout" in str(e) or "Response error" in str(e)):
                    print("Authentication error detected in utils.py - raising to trigger device reconnection...")
                    raise e  # Re-raise to let calling function handle reconnection

                if retry_count == max_retries:
                    print(f"Failed to get energy data after {max_retries} attempts: {e}")
                    await asyncio.sleep(max_delay)
                    continue
                await asyncio.sleep(min(2 ** retry_count, max_delay))
    # concat dicts to one
    df_energy_consumption = []
    for i_quarter_m1, dict_energy_data in enumerate(list_dict_energy_data_daily):
        quarter_start_month = 3 * i_quarter_m1 + 1
        df_energy_consumption.append(get_date_df_from_dict(dict_energy_data, quarter_start_month))
    
    # Handle case when no data was fetched
    if not df_energy_consumption:
        print("No energy data available - returning empty DataFrame")
        empty_df = pd.DataFrame(columns=['Date', 'Value'])
        empty_df.set_index('Date', inplace=True)
        return empty_df
    
    df_energy_consumption = pd.concat(df_energy_consumption)
    # delete dates that are in the future
    df_energy_consumption = df_energy_consumption[df_energy_consumption['Date'] <= datetime.today().strftime('%Y-%m-%d')]
    df_energy_consumption.set_index('Date', inplace=True)
    return df_energy_consumption


def get_awtrix_client():
    """Get configured Awtrix client from environment variables"""
    load_dotenv()
    awtrix_host = os.getenv("AWTRIX_HOST", "192.168.178.108")  # Default IP
    awtrix_port = int(os.getenv("AWTRIX_PORT", "80"))  # Default port (HTTP standard)
    return AwtrixClient(awtrix_host, awtrix_port)


async def monitor_power_and_notify_enhanced(device, user, device_name="Device", threshold_high=50, threshold_low=10, 
                                          duration_minutes=5, message="", high_power_threshold=1000, 
                                          max_retries=3, max_delay=60, enable_awtrix=True):
    """Enhanced power monitoring with both Pushover and Awtrix notifications"""
    power_exceeded = False
    low_power_start_time = None
    sensor_name = 'current_power'
    last_high_power_alert = None
    last_power_log = None
    log_interval = 300  # Log power reading only every 5 minutes
    
    # Initialize Awtrix client if enabled
    awtrix_client = get_awtrix_client() if enable_awtrix else None
    if enable_awtrix:
        logger.info(f"Awtrix enabled for {device_name}. Client initialized: {awtrix_client is not None}")
        if awtrix_client:
            logger.info(f"Awtrix client configured for host: {os.getenv('AWTRIX_HOST', '192.168.178.108')}:{os.getenv('AWTRIX_PORT', '80')}")
    else:
        logger.info(f"Awtrix disabled for {device_name}")
    
    while True:
        retry_count = 0
        current_power = None
        current_time = datetime.now()
        
        while retry_count < max_retries:
            try:
                current_power = (await device.get_current_power()).to_dict()
                
                # Log power reading only every 5 minutes or if significant change
                should_log = (last_power_log is None or 
                             (current_time - last_power_log).total_seconds() >= log_interval)
                
                if should_log:
                    logger.info(f"{device_name} current power: {current_power[sensor_name]}W")
                    last_power_log = current_time
                
                break
            except Exception as e:
                retry_count += 1
                if retry_count == max_retries:
                    logger.error(f"Failed to get power for {device_name} after {max_retries} attempts: {e}")
                    await asyncio.sleep(max_delay)
                    continue
                await asyncio.sleep(min(2 ** retry_count, max_delay))

        if current_power is None:
            continue

        current_power_value = current_power[sensor_name]
        
        # Check for high power consumption alert
        if enable_awtrix and current_power_value > high_power_threshold:
            now = datetime.now()
            logger.warning(f"High power detected: {current_power_value}W > {high_power_threshold}W for {device_name}")
            # Only send alert if more than 10 minutes passed since last alert
            if last_high_power_alert is None or (now - last_high_power_alert).seconds > 600:
                if awtrix_client:
                    logger.info(f"Sending Awtrix energy alert for {device_name}: {current_power_value}W")
                    success = awtrix_client.send_energy_alert(current_power_value, device_name)
                    logger.info(f"Awtrix energy alert result for {device_name}: {success}")
                else:
                    logger.warning(f"Awtrix client not available for energy alert for {device_name}")
                last_high_power_alert = now
            else:
                time_since_last = (now - last_high_power_alert).seconds
                logger.debug(f"High power alert suppressed for {device_name} - only {time_since_last}s since last alert (need 600s)")

        # Original appliance completion logic
        if current_power_value > threshold_high:
            power_exceeded = True
            low_power_start_time = None  # Reset since power is high again

        if power_exceeded and current_power_value < threshold_low:
            if low_power_start_time is None:
                low_power_start_time = datetime.now()
            elif datetime.now() - low_power_start_time > timedelta(minutes=duration_minutes):
                # Send both notifications
                logger.info(f"Appliance {device_name} completed cycle - sending notifications")
                send_pushover_notification_new(user=user, message=message)
                if enable_awtrix and awtrix_client:
                    logger.info(f"Sending Awtrix appliance completion for {device_name}")
                    success = awtrix_client.send_appliance_done(device_name)
                    logger.info(f"Awtrix appliance completion result for {device_name}: {success}")
                else:
                    logger.warning(f"Awtrix not enabled or client unavailable for appliance completion for {device_name}")
                
                power_exceeded = False  # Reset condition
                low_power_start_time = None  # Reset timer
        else:
            low_power_start_time = None  # Reset if current power is not low

        await asyncio.sleep(20)  # Check every 20 seconds


async def monitor_all_devices_power(devices_config, high_power_threshold=1000, enable_awtrix=True, 
                                  enable_status_display=True, status_interval_minutes=10):
    """Monitor all devices for high power consumption and send alerts"""
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    
    from tapo import ApiClient
    client = ApiClient(tapo_username, tapo_password)
    
    awtrix_client = get_awtrix_client() if enable_awtrix else None
    last_alerts = {}  # Track last alert time for each device
    last_status_display = None  # Track last status display time
    device_power_cache = {}  # Cache current power readings
    
    while True:
        for device_name, device_ip in devices_config.items():
            try:
                device = await client.p110(device_ip)
                current_power = (await device.get_current_power()).to_dict()
                power_value = current_power['current_power']
                
                # Cache the power value for status display
                device_power_cache[device_name] = power_value
                
                logger.info(f"{device_name}: {power_value}W")
                
                # Check for high power threshold alerts
                if power_value > high_power_threshold:
                    now = datetime.now()
                    # Only alert if more than 10 minutes since last alert for this device
                    if (device_name not in last_alerts or 
                        (now - last_alerts[device_name]).seconds > 600):
                        
                        if awtrix_client:
                            logger.info(f"Sending Awtrix energy alert for {device_name}: {power_value}W")
                            success = awtrix_client.send_energy_alert(power_value, device_name)
                            logger.info(f"Awtrix energy alert result for {device_name}: {success}")
                        else:
                            logger.warning(f"Awtrix client not available for energy alert for {device_name}")
                        
                        last_alerts[device_name] = now
                        
            except Exception as e:
                logger.error(f"Error monitoring {device_name}: {e}")
                device_power_cache[device_name] = None  # Mark as unavailable
                continue
        
        # Check if it's time for status display (every X minutes)
        now = datetime.now()
        if (enable_status_display and enable_awtrix and awtrix_client and 
            device_power_cache and  # Only if we have device data
            (last_status_display is None or 
             (now - last_status_display).total_seconds() >= status_interval_minutes * 60)):
            
            print(f"\n📊 Displaying device status cycle...")
            await display_device_status_cycle(awtrix_client, device_power_cache)
            last_status_display = now
        
        await asyncio.sleep(30)  # Check every 30 seconds


async def display_device_status_cycle(awtrix_client, device_power_cache, display_duration_seconds=4):
    """Display cycling status of all devices on Awtrix"""
    
    # Filter out devices with no data and sort by power consumption (highest first)
    valid_devices = {name: power for name, power in device_power_cache.items() if power is not None}
    sorted_devices = sorted(valid_devices.items(), key=lambda x: x[1], reverse=True)
    
    if not sorted_devices:
        print("⚠️  No valid device data for status display")
        return
    
    print(f"🔄 Cycling through {len(sorted_devices)} devices...")
    
    for i, (device_name, power_value) in enumerate(sorted_devices):
        try:
            # Determine color based on power consumption
            if power_value < 100:
                color = "#00FF00"  # Green - Low power
                icon = "128994"    # Green circle
            elif power_value < 500:
                color = "#FFFF00"  # Yellow - Medium power
                icon = "128993"    # Yellow circle
            elif power_value < 1000:
                color = "#FF6600"  # Orange - High power
                icon = "128992"    # Orange circle
            else:
                color = "#FF0000"  # Red - Very high power
                icon = "128308"    # Red circle
            
            # Create status message
            message_text = f"{device_name}: {power_value:.0f}W"
            
            # Send to Awtrix
            from awtrix_client import AwtrixMessage
            status_message = AwtrixMessage(
                text=message_text,
                icon=icon,
                color=color,
                duration=display_duration_seconds
            )
            
            success = awtrix_client.send_notification(status_message)
            if success:
                print(f"  📱 {i+1}/{len(sorted_devices)}: {message_text}")
            else:
                print(f"  ❌ Failed to display: {message_text}")
            
            # Wait for display duration before showing next device
            # (except for the last device, let it display naturally)
            if i < len(sorted_devices) - 1:
                await asyncio.sleep(display_duration_seconds)
                
        except Exception as e:
            print(f"  ❌ Error displaying {device_name}: {e}")
            continue
    
    print(f"✅ Status cycle completed!\n")
