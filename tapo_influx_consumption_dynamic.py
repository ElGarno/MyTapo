import asyncio
import os
import json
import logging
from threading import Lock
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from tapo import ApiClient
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

logging.basicConfig(level=logging.INFO)
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
                    # Only load enabled devices
                    self.devices = {
                        name: device_config['ip'] 
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

class InfluxWriter:
    def __init__(self):
        load_dotenv()
        influx_host = os.getenv("INFLUXDB_HOST", "192.168.178.114")
        influx_port = os.getenv("INFLUXDB_PORT", "8088")
        self.influx_url = f"http://{influx_host}:{influx_port}"
        self.influx_token = os.getenv("INFLUXDB_TOKEN")
        self.influx_org = "None"
        self.influx_bucket = os.getenv("INFLUXDB_BUCKET", "power_consumption")
        
    async def write_power_data(self, device_name, power_value):
        try:
            with InfluxDBClient(url=self.influx_url, token=self.influx_token, org=self.influx_org) as influx_client:
                write_api = influx_client.write_api(write_options=SYNCHRONOUS)
                
                point = Point("power_consumption") \
                    .tag("device", device_name) \
                    .field("power", power_value)
                    
                write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=point)
                logger.debug(f"Wrote {device_name}: {power_value}W to InfluxDB")
        except Exception as e:
            logger.error(f"Failed to write to InfluxDB for {device_name}: {e}")

async def fetch_and_write_data(device_manager, influx_writer, tapo_client):
    devices = device_manager.get_devices()
    
    tasks = []
    for device_name, ip in devices.items():
        task = asyncio.create_task(process_device(device_name, ip, tapo_client, influx_writer))
        tasks.append(task)
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

async def process_device(device_name, ip, tapo_client, influx_writer):
    try:
        device = await tapo_client.p110(ip)
        power_data = await device.get_current_power()
        await influx_writer.write_power_data(device_name, power_data.current_power)
    except Exception as e:
        logger.error(f"Failed to get power for device {device_name} ({ip}): {e}")

async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    
    if not tapo_username or not tapo_password:
        logger.error("TAPO credentials not found in environment variables")
        return
    
    device_manager = DeviceManager()
    influx_writer = InfluxWriter()
    tapo_client = ApiClient(tapo_username, tapo_password)
    
    logger.info("Starting dynamic device monitoring...")
    
    try:
        while True:
            await fetch_and_write_data(device_manager, influx_writer, tapo_client)
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        device_manager.stop_watcher()

if __name__ == "__main__":
    asyncio.run(main())