#!/usr/bin/env python3
"""
Awtrix Energy Monitor
Comprehensive energy monitoring with Awtrix display notifications
"""

import asyncio
import os
import json
from datetime import datetime
from tapo import ApiClient
from dotenv import load_dotenv
from awtrix_client import AwtrixClient
from utils import monitor_all_devices_power, get_awtrix_client


async def test_awtrix_connection():
    """Test connection to Awtrix device"""
    print("Testing Awtrix connection...")
    awtrix_client = get_awtrix_client()
    
    if awtrix_client.test_connection():
        print("✅ Awtrix device is reachable")
        
        # Send test notification
        success = awtrix_client.send_simple_message(
            "Hello from MyTapo!", 
            icon="128512",  # Smiley face
            duration=5
        )
        if success:
            print("✅ Test notification sent successfully")
        else:
            print("❌ Failed to send test notification")
        
        return True
    else:
        print("❌ Cannot reach Awtrix device")
        return False


def load_device_config():
    """Load device configuration from config/devices.json or environment variables"""
    config_file = "config/devices.json"
    
    if os.path.exists(config_file):
        print(f"Loading device config from {config_file}")
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            return {
                name: device_config['ip'] 
                for name, device_config in config['devices'].items() 
                if device_config.get('enabled', True)
            }
        except Exception as e:
            print(f"Error loading config file: {e}")
    
    # Fallback to environment variables
    print("Loading device config from environment variables")
    load_dotenv()
    
    devices = {}
    
    # Add known devices from environment
    env_devices = [
        ("Solar", "SOLAR_IP_ADDRESS"),
        ("Washing Machine", "WASHING_MACHINE_IP_ADDRESS"),
        ("Dryer", "WASHING_DRYER_IP_ADDRESS"),
    ]
    
    for name, env_var in env_devices:
        ip = os.getenv(env_var)
        if ip:
            devices[name] = ip
    
    return devices


async def send_manual_test_notifications():
    """Send various test notifications to Awtrix"""
    awtrix_client = get_awtrix_client()
    
    print("\nSending test notifications...")
    
    # Test energy alert
    print("Sending energy alert test...")
    awtrix_client.send_energy_alert(1250.5, "Test Device")
    await asyncio.sleep(3)
    
    # Test appliance completion
    print("Sending appliance completion test...")
    awtrix_client.send_appliance_done("Test Washing Machine")
    await asyncio.sleep(3)
    
    # Test solar report
    print("Sending solar report test...")
    awtrix_client.send_solar_report(15.3, 4.28)
    await asyncio.sleep(3)
    
    print("Test notifications complete!")


async def monitor_energy_with_awtrix():
    """Main monitoring function with Awtrix notifications"""
    print("Starting energy monitoring with Awtrix notifications...")
    
    # Load device configuration
    devices = load_device_config()
    print(f"Monitoring {len(devices)} devices: {list(devices.keys())}")
    
    if not devices:
        print("❌ No devices configured for monitoring")
        return
    
    # Start monitoring all devices for high power consumption
    await monitor_all_devices_power(
        devices, 
        high_power_threshold=1000, 
        enable_awtrix=True
    )


async def main():
    """Main function with menu options"""
    load_dotenv()
    
    print("🔌 MyTapo Awtrix Energy Monitor")
    print("=" * 40)
    
    while True:
        print("\nSelect an option:")
        print("1. Test Awtrix connection")
        print("2. Send test notifications")
        print("3. Start energy monitoring with Awtrix")
        print("4. Monitor specific device power")
        print("5. Exit")
        
        choice = input("\nEnter your choice (1-5): ").strip()
        
        if choice == "1":
            await test_awtrix_connection()
            
        elif choice == "2":
            if await test_awtrix_connection():
                await send_manual_test_notifications()
            
        elif choice == "3":
            try:
                await monitor_energy_with_awtrix()
            except KeyboardInterrupt:
                print("\n🛑 Monitoring stopped by user")
                break
                
        elif choice == "4":
            devices = load_device_config()
            if not devices:
                print("❌ No devices configured")
                continue
                
            print("\nAvailable devices:")
            device_list = list(devices.items())
            for i, (name, ip) in enumerate(device_list, 1):
                print(f"{i}. {name} ({ip})")
            
            try:
                device_choice = int(input("\nSelect device number: ")) - 1
                if 0 <= device_choice < len(device_list):
                    device_name, device_ip = device_list[device_choice]
                    print(f"\nMonitoring {device_name} for high power consumption...")
                    
                    # Monitor single device
                    single_device = {device_name: device_ip}
                    await monitor_all_devices_power(
                        single_device, 
                        high_power_threshold=1000, 
                        enable_awtrix=True
                    )
                else:
                    print("❌ Invalid device selection")
            except (ValueError, KeyboardInterrupt):
                print("❌ Invalid input or operation cancelled")
                
        elif choice == "5":
            print("👋 Goodbye!")
            break
            
        else:
            print("❌ Invalid choice. Please select 1-5.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Program interrupted by user")
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")