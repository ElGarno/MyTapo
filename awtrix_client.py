import requests
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AwtrixMessage:
    """Data class for Awtrix notification messages"""
    text: str
    icon: Optional[str] = None
    color: Optional[str] = None
    duration: Optional[int] = None
    hold: Optional[bool] = None
    sound: Optional[str] = None
    priority: Optional[int] = None
    rainbow: Optional[bool] = None
    repeat: Optional[int] = None


class AwtrixClient:
    """Client for sending notifications to Awtrix displays"""
    
    def __init__(self, host: str, port: int = 80, timeout: int = 10):
        """
        Initialize Awtrix client
        
        Args:
            host: IP address or hostname of Awtrix device
            port: Port number (default: 80 for HTTP)
            timeout: Request timeout in seconds
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        # Only include port in URL if it's not the standard HTTP port (80)
        if port == 80:
            self.base_url = f"http://{host}/api"
        else:
            self.base_url = f"http://{host}:{port}/api"
        
    def send_notification(self, message: AwtrixMessage) -> bool:
        """
        Send a notification to the Awtrix display
        
        Args:
            message: AwtrixMessage object containing notification details
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            url = f"{self.base_url}/notify"
            
            # Build payload from message
            payload = {"text": message.text}
            
            if message.icon:
                payload["icon"] = message.icon
            if message.color:
                payload["color"] = message.color
            if message.duration:
                payload["duration"] = message.duration
            if message.hold is not None:
                payload["hold"] = message.hold
            if message.sound:
                payload["sound"] = message.sound
            if message.priority is not None:
                payload["priority"] = message.priority
            if message.rainbow is not None:
                payload["rainbow"] = message.rainbow
            if message.repeat is not None:
                payload["repeat"] = message.repeat
                
            logger.info(f"Sending notification to Awtrix: {payload}")
            
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                logger.info("Notification sent successfully")
                return True
            else:
                logger.error(f"Failed to send notification. Status: {response.status_code}, Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error sending notification: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending notification: {e}")
            return False
    
    def send_app_data(self, app_name: str, data: Dict[str, Any]) -> bool:
        """
        Send app data to Awtrix display (for custom apps)
        
        Args:
            app_name: Name of the app
            data: Dictionary containing app data
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            url = f"{self.base_url}/custom/{app_name}"
            
            logger.info(f"Sending app data to Awtrix: {app_name} - {data}")
            
            response = requests.post(
                url,
                json=data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                logger.info(f"App data sent successfully to {app_name}")
                return True
            else:
                logger.error(f"Failed to send app data. Status: {response.status_code}, Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error sending app data: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending app data: {e}")
            return False
    
    def test_connection(self) -> bool:
        """
        Test connection to Awtrix device
        
        Returns:
            bool: True if device is reachable, False otherwise
        """
        try:
            url = f"{self.base_url}/stats"
            response = requests.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                logger.info("Awtrix device is reachable")
                return True
            else:
                logger.error(f"Awtrix device responded with status: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Cannot reach Awtrix device: {e}")
            return False
    
    def send_simple_message(self, text: str, icon: Optional[str] = None, duration: int = 10) -> bool:
        """
        Send a simple text message
        
        Args:
            text: Message text
            icon: Optional icon name or number
            duration: Display duration in seconds
            
        Returns:
            bool: True if successful, False otherwise
        """
        message = AwtrixMessage(
            text=text,
            icon=icon,
            duration=duration
        )
        return self.send_notification(message)
    
    def send_energy_alert(self, power_watts: float, device_name: str) -> bool:
        """
        Send energy consumption alert
        
        Args:
            power_watts: Power consumption in watts
            device_name: Name of the device
            
        Returns:
            bool: True if successful, False otherwise
        """
        message = AwtrixMessage(
            text=f"{device_name}: {power_watts:.0f}W",
            icon="32491",  # Electric plug LaMetric icon
            color="#FF6600",  # Orange color for alerts
            duration=15,
            sound="beep"
        )
        return self.send_notification(message)
    
    def send_appliance_done(self, appliance_name: str) -> bool:
        """
        Send appliance completion notification
        
        Args:
            appliance_name: Name of the appliance (e.g., "Washing Machine", "Dryer")
            
        Returns:
            bool: True if successful, False otherwise
        """
        icon_map = {
            "washing": "26673",   # Washing machine LaMetric icon
            "dryer": "56907",    # Dryer LaMetric icon (original)
            "dishwasher": "24501"  # Dishwasher LaMetric icon (original)
        }
        
        # Try to find appropriate icon
        icon = None
        for key, icon_code in icon_map.items():
            if key.lower() in appliance_name.lower():
                icon = icon_code
                break
        
        message = AwtrixMessage(
            text=f"{appliance_name} Done!",
            icon=icon or "4474",  # Default checkmark emoji
            color="#00FF00",  # Green color for completion
            duration=20,
            sound="chime",
            priority=2
        )
        return self.send_notification(message)
    
    def send_solar_report(self, energy_kwh: float, savings_eur: float) -> bool:
        """
        Send solar energy generation report
        
        Args:
            energy_kwh: Energy generated in kWh
            savings_eur: Money saved in EUR
            
        Returns:
            bool: True if successful, False otherwise
        """
        message = AwtrixMessage(
            text=f"Solar: {energy_kwh:.2f}kWh €{savings_eur:.2f}",
            icon="27464",  # Sun emoji
            color="#FFD700",  # Gold color
            duration=15
        )
        return self.send_notification(message)