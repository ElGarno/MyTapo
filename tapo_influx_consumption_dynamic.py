import asyncio
import os
import json
import logging
from threading import Lock
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from tapo import ApiClient
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from utils import get_awtrix_client
from influx_batch_writer import InfluxBatchWriter

# Configure logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class DeviceConfigHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback
        
    def on_modified(self, event):
        if event.src_path.endswith('devices.json'):
            logger.info("Device config file changed, reloading...")
            self.callback()

class DeviceManager:
    def __init__(self, config_path="config/devices.json"):
        self.config_path = Path(config_path)
        self.devices = {}
        self.lock = Lock()
        self.load_config()
        self.setup_file_watcher()
        
    def load_config(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                with self.lock:
                    # Load full device config for enabled devices
                    self.devices = {
                        name: {
                            'ip': device_config['ip'],
                            'emoji_id': device_config.get('emoji_id'),
                            'description': device_config.get('description', name)
                        }
                        for name, device_config in config['devices'].items() 
                        if device_config.get('enabled', True)
                    }
                logger.info(f"Loaded {len(self.devices)} enabled devices")
            else:
                logger.warning(f"Config file {self.config_path} not found")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            
    def setup_file_watcher(self):
        event_handler = DeviceConfigHandler(self.load_config)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.config_path.parent), recursive=False)
        self.observer.start()
        
    def get_devices(self):
        with self.lock:
            return self.devices.copy()
            
    def stop_watcher(self):
        self.observer.stop()
        self.observer.join()

# Legacy InfluxWriter class removed - now using InfluxBatchWriter for 90% fewer connections

async def fetch_and_write_data(device_manager, influx_writer, tapo_client):
    """
    Fetch power data from all devices and write to InfluxDB in a single batch.
    This reduces connections from 11/cycle to 1/cycle (90% reduction).
    """
    devices = device_manager.get_devices()
    device_power_data = {}

    # Fetch all device power readings concurrently
    tasks = []
    for device_name, device_config in devices.items():
        ip = device_config['ip']
        task = asyncio.create_task(process_device(device_name, ip, tapo_client))
        tasks.append(task)

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results: add to batch writer and collect for Awtrix
        for i, (device_name, _) in enumerate(devices.items()):
            if i < len(results) and not isinstance(results[i], Exception):
                power_value = results[i]
                if power_value is not None:
                    # Add to batch (accumulated, not written yet)
                    influx_writer.add_power_measurement(device_name, power_value)
                    device_power_data[device_name] = power_value

        # Write all device data in a single batch operation
        if influx_writer.batch_size() > 0:
            success = await influx_writer.flush()
            if not success:
                logger.error(f"Failed to write batch of {influx_writer.batch_size()} measurements")

    return device_power_data

async def process_device(device_name, ip, tapo_client):
    """
    Fetch power data from a single device.
    No longer writes directly - data is accumulated in batch by calling function.
    """
    try:
        device = await tapo_client.p110(ip)
        power_data = await device.get_current_power()
        power_value = power_data.current_power

        logger.debug(f"{device_name}: {power_value}W")
        return power_value
    except Exception as e:
        logger.error(f"Failed to get power for device {device_name} ({ip}): {e}")
        return None

async def display_device_carousel(awtrix_client, device_power_data, device_manager):
    """Display each device's power consumption for 5 seconds"""
    if not device_power_data:
        return
    
    # Filter out None values and sort devices by power consumption (highest first)
    valid_devices = {name: power for name, power in device_power_data.items() if power is not None}
    if not valid_devices:
        logger.warning("No valid device power data for carousel")
        return
        
    sorted_devices = sorted(valid_devices.items(), key=lambda x: x[1], reverse=True)
    devices_config = device_manager.get_devices()
    
    logger.info(f"Starting device carousel with {len(sorted_devices)} devices")
    
    for device_name, power_value in sorted_devices:
        try:
            # Get emoji_id from device config
            device_config = devices_config.get(device_name, {})
            emoji_id = device_config.get('emoji_id')
            
            # Determine color and circle icon based on power consumption
            if power_value < 50:
                color = "#00FF00"  # Green - Low power
                circle_icon = "27070"    # Green circle
            elif power_value < 200:
                color = "#FFFF00"  # Yellow - Medium power
                circle_icon = "27067"    # Yellow circle
            elif power_value < 1000:
                color = "#FF6600"  # Orange - High power
                circle_icon = "27072"    # Orange circle
            else:
                color = "#FF0000"  # Red - Very high power
                circle_icon = "27068"    # Red circle
            
            # Use emoji if available, otherwise use circle
            icon = str(emoji_id) if emoji_id else circle_icon
            
            from awtrix_client import AwtrixMessage
            message = AwtrixMessage(
                text=f"{device_name}: {power_value:.0f}W",
                icon=icon,
                color=color,
                duration=5
            )
            
            success = awtrix_client.send_notification(message)
            if success:
                emoji_info = f"emoji: {emoji_id}" if emoji_id else f"circle: {circle_icon}"
                logger.info(f"✅ Carousel displayed: {device_name} {power_value:.0f}W ({emoji_info})")
            else:
                logger.error(f"❌ Failed to display carousel: {device_name}")
            
            await asyncio.sleep(5)  # Wait 5 seconds before next device
            
        except Exception as e:
            logger.error(f"Error displaying {device_name}: {e}")


async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    
    if not tapo_username or not tapo_password:
        logger.error("TAPO credentials not found in environment variables")
        return
    
    device_manager = DeviceManager()
    influx_writer = InfluxBatchWriter()  # Now using batch writer for 90% fewer connections
    tapo_client = ApiClient(tapo_username, tapo_password)
    awtrix_client = get_awtrix_client()
    
    # Log Awtrix configuration
    awtrix_host = os.getenv("AWTRIX_HOST", "192.168.178.108")
    awtrix_port = os.getenv("AWTRIX_PORT", "80")
    logger.info(f"Awtrix client configured for {awtrix_host}:{awtrix_port}")
    
    # Test Awtrix connection
    if awtrix_client and awtrix_client.test_connection():
        logger.info("Awtrix device connection test successful")
    else:
        logger.warning("Awtrix device connection test failed")
    
    logger.info("Starting dynamic device monitoring with Awtrix notifications...")
    
    last_carousel_time = None
    
    try:
        while True:
            # Fetch and write data to InfluxDB
            device_power_data = await fetch_and_write_data(device_manager, influx_writer, tapo_client)
            logger.debug(f"Fetched power data for {len(device_power_data)} devices")
            
            # Display device carousel every 5 minutes
            current_time = datetime.now()
            if (device_power_data and 
                (last_carousel_time is None or 
                 (current_time - last_carousel_time).total_seconds() >= 300)):  # 5 minutes
                
                logger.info(f"Time for device carousel - {len(device_power_data)} devices available")
                await display_device_carousel(awtrix_client, device_power_data, device_manager)
                last_carousel_time = current_time
            elif device_power_data:
                time_until_next = 300 - (current_time - last_carousel_time).total_seconds() if last_carousel_time else 300
                logger.debug(f"Next carousel in {time_until_next:.0f} seconds")
            
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        device_manager.stop_watcher()

if __name__ == "__main__":
    asyncio.run(main())