import httpx
from dotenv import load_dotenv
import os

def send_pushover_notification(user, message):
    load_dotenv()
    pushover_api_token = os.getenv("PUSHOVER_TAPO_API_TOKEN")

    response = httpx.post("https://api.pushover.net/1/messages.json", data={
        "token": pushover_api_token,
        "user": user,
        "message": message,
    })
    print(response.text)