import asyncio
import os
from tapo import ApiClient
from dotenv import load_dotenv

from utils import monitor_power_and_notify


async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    pushover_user_group = os.getenv("PUSHOVER_USER_GROUP_WOERIS")
    wasching_machine_ip_address = os.getenv("WASCHING_MACHINE_IP_ADDRESS")

    client = ApiClient(tapo_username, tapo_password)
    device_wasching_machine = await client.p110(wasching_machine_ip_address)
    await monitor_power_and_notify(device=device_wasching_machine, user=pushover_user_group, message="Die Wäsche ist fertig, Tapsi! 🧺🐶")

if __name__ == "__main__":
    asyncio.run(main())
