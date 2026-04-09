import asyncio
import os
import logging
from tapo import ApiClient
from dotenv import load_dotenv

from utils import monitor_power_and_notify_enhanced

logger = logging.getLogger(__name__)


async def main():
    load_dotenv()
    tapo_username = os.getenv("TAPO_USERNAME")
    tapo_password = os.getenv("TAPO_PASSWORD")
    pushover_user_group = os.getenv("PUSHOVER_USER_GROUP_WOERIS")
    washing_dryer_ip_address = os.getenv("WASHING_DRYER_IP_ADDRESS")

    client = ApiClient(tapo_username, tapo_password)
    await monitor_power_and_notify_enhanced(
        client=client,
        device_ip=washing_dryer_ip_address,
        user=pushover_user_group,
        device_name="Dryer",
        threshold_high=40,
        threshold_low=10,
        duration_minutes=3,
        message="Der Trockner ist fertig. Bitte die Wäsche entnehmen. 🧺🧦👚👖🧦🧺",
        high_power_threshold=1000,
        enable_awtrix=True,
        loop_sound=True
    )

if __name__ == "__main__":
    asyncio.run(main())