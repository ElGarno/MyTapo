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
    wasching_dryer_ip_address = os.getenv("WASCHING_DRYER_IP_ADDRESS")

    client = ApiClient(tapo_username, tapo_password)
    device_wasching_dryer = await client.p110(wasching_dryer_ip_address)
    await monitor_power_and_notify(device=device_wasching_dryer, user=pushover_user_group, threshold_high=40, threshold_low=10, duration_minutes=3,
                                   message="Der Trocker ist fertig. Bitte die Wäsche entnehmen. 🧺🧦👚👖🧦🧺")

if __name__ == "__main__":
    asyncio.run(main())

