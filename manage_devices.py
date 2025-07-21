#!/usr/bin/env python3
"""
Device Management Utility for MyTapo
Usage: python manage_devices.py [add|remove|list|enable|disable] [device_name] [ip] [description]
"""

import json
import sys
from pathlib import Path

CONFIG_PATH = Path("config/devices.json")

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {"devices": {}}

def save_config(config):
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

def add_device(name, ip, description=""):
    config = load_config()
    config["devices"][name] = {
        "ip": ip,
        "enabled": True,
        "description": description
    }
    save_config(config)
    print(f"✅ Added device '{name}' ({ip})")

def remove_device(name):
    config = load_config()
    if name in config["devices"]:
        del config["devices"][name]
        save_config(config)
        print(f"❌ Removed device '{name}'")
    else:
        print(f"❌ Device '{name}' not found")

def toggle_device(name, enabled):
    config = load_config()
    if name in config["devices"]:
        config["devices"][name]["enabled"] = enabled
        save_config(config)
        status = "enabled" if enabled else "disabled"
        print(f"🔄 {name} {status}")
    else:
        print(f"❌ Device '{name}' not found")

def list_devices():
    config = load_config()
    print(f"\n📱 MyTapo Devices ({len(config['devices'])} total):")
    print("-" * 60)
    for name, device in config["devices"].items():
        status = "🟢 ON " if device["enabled"] else "🔴 OFF"
        print(f"{status} {name:<20} {device['ip']:<15} {device.get('description', '')}")
    print()

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    command = sys.argv[1].lower()
    
    if command == "list":
        list_devices()
    elif command == "add" and len(sys.argv) >= 4:
        name, ip = sys.argv[2], sys.argv[3]
        description = sys.argv[4] if len(sys.argv) > 4 else ""
        add_device(name, ip, description)
    elif command == "remove" and len(sys.argv) >= 3:
        remove_device(sys.argv[2])
    elif command == "enable" and len(sys.argv) >= 3:
        toggle_device(sys.argv[2], True)
    elif command == "disable" and len(sys.argv) >= 3:
        toggle_device(sys.argv[2], False)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()