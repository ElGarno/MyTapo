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

    while True:
        try:
            client = ApiClient(tapo_username, tapo_password)
            device_washing_dryer = await client.p110(washing_dryer_ip_address)
            logger.info("Dryer: ApiClient and device handle created")

            await monitor_power_and_notify_enhanced(
                device=device_washing_dryer,
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
        except Exception as e:
            logger.warning(f"Dryer: Session error ({e}), recreating ApiClient in 10s...")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())