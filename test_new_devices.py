#!/usr/bin/env python3
"""Test script to diagnose new device connectivity issues"""

import asyncio
import os
from tapo import ApiClient
from dotenv import load_dotenv

async def test_device(client, ip, name):
    """Test connection to a single device"""
    print(f"\n{'='*60}")
    print(f"Testing {name} ({ip})...")
    print('='*60)

    try:
        # Try to connect
        print(f"1️⃣  Attempting to connect to device...")
        device = await client.p110(ip)
        print(f"✅ Connection established!")

        # Try to get device info
        print(f"2️⃣  Getting device info...")
        device_info = await device.get_device_info()
        print(f"✅ Device Info Retrieved:")
        print(f"   - Model: {device_info.model}")
        print(f"   - Nickname: {device_info.nickname}")
        print(f"   - Device ID: {device_info.device_id}")
        print(f"   - Hardware Version: {device_info.hw_ver}")
        print(f"   - Firmware Version: {device_info.fw_ver}")

        # Try to get current power
        print(f"3️⃣  Getting current power reading...")
        power = await device.get_current_power()
        print(f"✅ Current Power: {power.current_power}W")

        print(f"\n🎉 {name} is working perfectly!")
        return True

    except Exception as e:
        print(f"\n❌ Error with {name}:")
        print(f"   Error Type: {type(e).__name__}")
        print(f"   Error Message: {e}")

        # Provide troubleshooting tips based on error
        error_str = str(e)
        if "403" in error_str or "Forbidden" in error_str:
            print(f"\n💡 Troubleshooting Tips:")
            print(f"   1. Check if device is added to Tapo app with account: {os.getenv('TAPO_USERNAME')}")
            print(f"   2. Try removing and re-adding device in Tapo app")
            print(f"   3. Make sure you're using the same Tapo account")
            print(f"   4. Device might be linked to a different account")
        elif "timeout" in error_str.lower():
            print(f"\n💡 Troubleshooting Tips:")
            print(f"   1. Device might be offline or unreachable")
            print(f"   2. Check if device is powered on")
            print(f"   3. Verify IP address is correct")

        return False

async def main():
    load_dotenv()

    print("🔍 MyTapo New Device Connectivity Test")
    print("="*60)

    username = os.getenv("TAPO_USERNAME")
    password = os.getenv("TAPO_PASSWORD")

    if not username or not password:
        print("❌ TAPO credentials not found in .env file!")
        return

    print(f"Using Tapo Account: {username}")

    # Create API client
    client = ApiClient(username, password)

    # Test new devices
    devices_to_test = [
        ("192.168.178.120", "Bathroom"),
        ("192.168.178.121", "Office2"),
    ]

    results = {}
    for ip, name in devices_to_test:
        results[name] = await test_device(client, ip, name)
        await asyncio.sleep(1)  # Brief pause between tests

    # Summary
    print("\n" + "="*60)
    print("📊 SUMMARY")
    print("="*60)
    for name, success in results.items():
        status = "✅ Working" if success else "❌ Failed"
        print(f"   {name}: {status}")

    if not all(results.values()):
        print("\n⚠️  Some devices failed. Check troubleshooting tips above.")
        print("   Most likely cause: Devices not added to Tapo account yet")
    else:
        print("\n🎉 All devices working!")

if __name__ == "__main__":
    asyncio.run(main())