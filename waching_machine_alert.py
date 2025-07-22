import asyncio
import os
from tapo import ApiClient
from dotenv import load_dotenv

from utils import monitor_power_and_notify_enhanced


async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    pushover_user_group = os.getenv("PUSHOVER_USER_GROUP_WOERIS")
    wasching_machine_ip_address = os.getenv("WASCHING_MACHINE_IP_ADDRESS")

    client = ApiClient(tapo_username, tapo_password)
    device_wasching_machine = await client.p110(wasching_machine_ip_address)
    await monitor_power_and_notify_enhanced(
        device=device_wasching_machine, 
        user=pushover_user_group, 
        device_name="Washing Machine",
        message="Die Wäsche ist fertig, Tapsi! 🧺🐶",
        high_power_threshold=1000,
        enable_awtrix=True
    )

if __name__ == "__main__":
    asyncio.run(main())
