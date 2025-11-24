"""
Connection pool manager for Tapo API clients.

This module provides efficient connection pooling and session management for Tapo devices,
reducing overhead from repeated authentication and device connections.
"""

import os
import logging
import asyncio
from typing import Dict, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv
from tapo import ApiClient
from retry_manager import async_retry_with_backoff, is_authentication_error

logger = logging.getLogger(__name__)


class TapoConnectionPool:
    """
    Connection pool for Tapo API clients with automatic session refresh.

    Features:
    - Reuses ApiClient instances across operations
    - Automatic session refresh every 2 hours (prevents timeouts)
    - Handles authentication errors with reconnection
    - Device connection caching

    Usage:
        pool = TapoConnectionPool(username, password)
        device = await pool.get_device("192.168.178.100")
        power = await device.get_current_power()
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        session_refresh_minutes: int = 120
    ):
        """
        Initialize connection pool.

        Args:
            username: Tapo account username (defaults to env TAPO_USERNAME)
            password: Tapo account password (defaults to env TAPO_PASSWORD)
            session_refresh_minutes: Minutes between automatic session refreshes (default 120)
        """
        load_dotenv()

        self.username = username or os.getenv("TAPO_USERNAME")
        self.password = password or os.getenv("TAPO_PASSWORD")

        if not self.username or not self.password:
            raise ValueError("Tapo credentials not provided")

        self.session_refresh_minutes = session_refresh_minutes
        self.client: Optional[ApiClient] = None
        self.client_created_at: Optional[datetime] = None
        self.device_cache: Dict[str, any] = {}
        self.device_created_at: Dict[str, datetime] = {}

        logger.info(f"Initialized TapoConnectionPool with {session_refresh_minutes}min session refresh")

    def _should_refresh_client(self) -> bool:
        """Check if client needs refresh based on age"""
        if self.client is None or self.client_created_at is None:
            return True

        age = (datetime.now() - self.client_created_at).total_seconds() / 60
        return age >= self.session_refresh_minutes

    def _create_client(self) -> ApiClient:
        """Create new ApiClient instance"""
        self.client = ApiClient(self.username, self.password)
        self.client_created_at = datetime.now()
        logger.info("Created new Tapo ApiClient")
        return self.client

    def get_client(self) -> ApiClient:
        """
        Get or create ApiClient instance with automatic refresh.

        Returns:
            ApiClient instance
        """
        if self._should_refresh_client():
            logger.info("Refreshing Tapo ApiClient (session refresh)")
            # Clear device cache when client refreshes
            self.device_cache.clear()
            self.device_created_at.clear()
            return self._create_client()

        return self.client

    async def get_device(
        self,
        ip_address: str,
        force_reconnect: bool = False
    ):
        """
        Get device connection with caching and automatic reconnection.

        Args:
            ip_address: Device IP address
            force_reconnect: Force new connection even if cached

        Returns:
            Tapo device instance (P110, L530, etc.)
        """
        # Check if we need to reconnect the device
        should_reconnect = (
            force_reconnect or
            ip_address not in self.device_cache or
            self._should_refresh_device(ip_address)
        )

        if should_reconnect:
            client = self.get_client()
            try:
                # Connect to P110 device
                device = await client.p110(ip_address)
                self.device_cache[ip_address] = device
                self.device_created_at[ip_address] = datetime.now()
                logger.debug(f"Connected to device {ip_address}")
                return device
            except Exception as e:
                logger.error(f"Failed to connect to device {ip_address}: {e}")
                # Remove from cache on failure
                self.device_cache.pop(ip_address, None)
                self.device_created_at.pop(ip_address, None)
                raise

        return self.device_cache[ip_address]

    def _should_refresh_device(self, ip_address: str) -> bool:
        """Check if device connection should be refreshed"""
        if ip_address not in self.device_created_at:
            return True

        age = (datetime.now() - self.device_created_at[ip_address]).total_seconds() / 60
        return age >= self.session_refresh_minutes

    async def get_device_power(
        self,
        ip_address: str,
        max_retries: int = 3
    ) -> Optional[float]:
        """
        Get current power reading from device with retry and auto-reconnect.

        Args:
            ip_address: Device IP address
            max_retries: Maximum retry attempts

        Returns:
            Power value in watts, or None on failure
        """
        for attempt in range(max_retries):
            try:
                device = await self.get_device(ip_address)
                power_data = await device.get_current_power()
                return power_data.current_power

            except Exception as e:
                # Check for auth errors - trigger reconnection
                if is_authentication_error(e):
                    logger.warning(f"Authentication error for {ip_address}, reconnecting...")
                    await self.reconnect_device(ip_address)

                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    else:
                        logger.error(f"Failed to get power from {ip_address} after {max_retries} attempts")
                        return None
                else:
                    logger.error(f"Error getting power from {ip_address}: {e}")
                    return None

        return None

    async def reconnect_device(self, ip_address: str) -> None:
        """
        Force reconnection to a device (clears cache and reconnects).

        Args:
            ip_address: Device IP address
        """
        logger.info(f"Forcing reconnection to device {ip_address}")
        self.device_cache.pop(ip_address, None)
        self.device_created_at.pop(ip_address, None)
        await self.get_device(ip_address, force_reconnect=True)

    async def reconnect_all(self) -> None:
        """Force reconnection to all cached devices"""
        logger.info("Reconnecting all devices in pool")
        self.device_cache.clear()
        self.device_created_at.clear()
        self._create_client()

    def get_pool_stats(self) -> Dict[str, any]:
        """
        Get statistics about the connection pool.

        Returns:
            Dictionary with pool stats
        """
        client_age_minutes = 0
        if self.client_created_at:
            client_age_minutes = (datetime.now() - self.client_created_at).total_seconds() / 60

        return {
            "client_age_minutes": client_age_minutes,
            "cached_devices": len(self.device_cache),
            "device_ips": list(self.device_cache.keys()),
            "session_refresh_minutes": self.session_refresh_minutes
        }


class TapoDeviceWrapper:
    """
    Wrapper for Tapo device with automatic retry and reconnection.

    Provides a more robust interface for device operations with built-in
    error handling and session management.
    """

    def __init__(self, pool: TapoConnectionPool, ip_address: str, device_name: str = "Device"):
        """
        Initialize device wrapper.

        Args:
            pool: TapoConnectionPool instance
            ip_address: Device IP address
            device_name: Human-readable device name for logging
        """
        self.pool = pool
        self.ip_address = ip_address
        self.device_name = device_name

    @async_retry_with_backoff(max_retries=3, max_delay=60, raise_on_auth_error=False)
    async def get_current_power(self) -> Optional[float]:
        """
        Get current power with automatic retry and reconnection.

        Returns:
            Power value in watts, or None on failure
        """
        try:
            device = await self.pool.get_device(self.ip_address)
            power_data = await device.get_current_power()
            return power_data.current_power
        except Exception as e:
            if is_authentication_error(e):
                logger.info(f"Auth error for {self.device_name}, reconnecting...")
                await self.pool.reconnect_device(self.ip_address)
                raise  # Let retry decorator handle it
            else:
                logger.error(f"Error getting power for {self.device_name}: {e}")
                raise

    @async_retry_with_backoff(max_retries=3, max_delay=60, raise_on_auth_error=False)
    async def get_energy_usage(self):
        """
        Get energy usage with automatic retry and reconnection.

        Returns:
            Energy usage data
        """
        try:
            device = await self.pool.get_device(self.ip_address)
            return await device.get_energy_usage()
        except Exception as e:
            if is_authentication_error(e):
                logger.info(f"Auth error for {self.device_name}, reconnecting...")
                await self.pool.reconnect_device(self.ip_address)
                raise  # Let retry decorator handle it
            else:
                logger.error(f"Error getting energy for {self.device_name}: {e}")
                raise

    @async_retry_with_backoff(max_retries=3, max_delay=60, raise_on_auth_error=False)
    async def get_device_info(self):
        """
        Get device info with automatic retry and reconnection.

        Returns:
            Device information
        """
        try:
            device = await self.pool.get_device(self.ip_address)
            return await device.get_device_info()
        except Exception as e:
            if is_authentication_error(e):
                logger.info(f"Auth error for {self.device_name}, reconnecting...")
                await self.pool.reconnect_device(self.ip_address)
                raise
            else:
                logger.error(f"Error getting device info for {self.device_name}: {e}")
                raise
