#!/usr/bin/env python3
"""Diagnose Tapo protocol issues with detailed logging"""

import asyncio
import os
from tapo import ApiClient
from dotenv import load_dotenv
import logging

# Enable DEBUG logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_device_detailed(ip, name):
    """Test device with multiple retry strategies"""
    print(f"\n{'='*70}")
    print(f"🔍 Detailed Test: {name} ({ip})")
    print('='*70)

    load_dotenv()
    username = os.getenv("TAPO_USERNAME")
    password = os.getenv("TAPO_PASSWORD")

    # Strategy 1: Try with fresh client
    print(f"\n📌 Strategy 1: Fresh client connection")
    try:
        client = ApiClient(username, password)
        device = await client.p110(ip)
        info = await device.get_device_info()
        print(f"✅ SUCCESS with fresh client!")
        print(f"   Model: {info.model}")
        print(f"   Firmware: {info.fw_ver}")
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")

    # Strategy 2: Try with delay
    print(f"\n📌 Strategy 2: With 2-second delay")
    try:
        await asyncio.sleep(2)
        client = ApiClient(username, password)
        device = await client.p110(ip)
        info = await device.get_device_info()
        print(f"✅ SUCCESS with delay!")
        print(f"   Model: {info.model}")
        print(f"   Firmware: {info.fw_ver}")
        return True
    except Exception as e:
        print(f"❌ Failed: {e}")

    # Strategy 3: Multiple retries
    print(f"\n📌 Strategy 3: Retry 3 times with exponential backoff")
    for attempt in range(3):
        try:
            await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
            print(f"   Attempt {attempt + 1}/3...")
            client = ApiClient(username, password)
            device = await client.p110(ip)
            info = await device.get_device_info()
            print(f"✅ SUCCESS on attempt {attempt + 1}!")
            print(f"   Model: {info.model}")
            print(f"   Firmware: {info.fw_ver}")
            return True
        except Exception as e:
            print(f"   Attempt {attempt + 1} failed: {e}")

    print(f"\n❌ All strategies failed for {name}")
    return False

async def compare_working_vs_broken():
    """Compare a working device with the broken ones"""
    print("\n" + "="*70)
    print("🔬 COMPARISON TEST: Working vs New Devices")
    print("="*70)

    load_dotenv()
    username = os.getenv("TAPO_USERNAME")
    password = os.getenv("TAPO_PASSWORD")
    client = ApiClient(username, password)

    # Test a known working device first
    working_ip = "192.168.178.52"  # washing_machine
    print(f"\n✅ Testing WORKING device: washing_machine ({working_ip})")
    try:
        device = await client.p110(working_ip)
        info = await device.get_device_info()
        print(f"   Model: {info.model}")
        print(f"   Firmware: {info.fw_ver}")
        print(f"   Hardware: {info.hw_ver}")
        print(f"   Protocol: {info.type}")
        working_fw = info.fw_ver
    except Exception as e:
        print(f"   Error: {e}")
        working_fw = "unknown"

    # Now test the broken devices
    for ip, name in [("192.168.178.120", "bathroom"), ("192.168.178.121", "office2")]:
        print(f"\n❌ Testing BROKEN device: {name} ({ip})")
        try:
            device = await client.p110(ip)
            info = await device.get_device_info()
            print(f"   Model: {info.model}")
            print(f"   Firmware: {info.fw_ver}")
            print(f"   Hardware: {info.hw_ver}")
            print(f"   Protocol: {info.type}")

            if info.fw_ver != working_fw:
                print(f"\n⚠️  FIRMWARE MISMATCH!")
                print(f"   Working device: {working_fw}")
                print(f"   This device: {info.fw_ver}")
                print(f"   → Try updating firmware in Tapo app")
        except Exception as e:
            print(f"   Error: {e}")
            print(f"   Can't retrieve device info (handshake failed)")

async def main():
    print("🔍 MyTapo Protocol Diagnostic Tool")

    # Test each new device thoroughly
    await test_device_detailed("192.168.178.120", "Bathroom")
    await test_device_detailed("192.168.178.121", "Office2")

    # Compare with working device
    await compare_working_vs_broken()

    print("\n" + "="*70)
    print("💡 RECOMMENDATIONS")
    print("="*70)
    print("If all strategies failed, try:")
    print("1. Update device firmware in Tapo app (Settings → Device Info → Update)")
    print("2. Restart the plugs (unplug for 10 seconds)")
    print("3. Check if devices have 'Local Control' enabled in Tapo app")
    print("4. Re-add devices to Tapo account")

if __name__ == "__main__":
    asyncio.run(main())