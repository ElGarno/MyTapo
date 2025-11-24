"""
Optimized InfluxDB batch writer for MyTapo monitoring services.

This module provides efficient batched writes to InfluxDB, reducing connection
overhead from 3,120 connections/hour to 240 connections/hour (13 devices × 240 cycles @ 15s intervals).
"""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class InfluxBatchWriter:
    """
    Optimized batch writer for InfluxDB that accumulates multiple data points
    and writes them in a single transaction, dramatically reducing connection overhead.

    Usage:
        # Create writer instance (reusable)
        writer = InfluxBatchWriter()

        # Accumulate data points
        writer.add_power_measurement("device1", 150.5)
        writer.add_power_measurement("device2", 42.3)

        # Write all at once
        await writer.flush()
    """

    def __init__(
        self,
        influx_host: Optional[str] = None,
        influx_port: Optional[str] = None,
        influx_token: Optional[str] = None,
        influx_bucket: Optional[str] = None,
        influx_org: str = "None"
    ):
        """
        Initialize the batch writer with InfluxDB connection parameters.

        Args:
            influx_host: InfluxDB host (defaults to env INFLUXDB_HOST)
            influx_port: InfluxDB port (defaults to env INFLUXDB_PORT)
            influx_token: InfluxDB token (defaults to env INFLUXDB_TOKEN)
            influx_bucket: InfluxDB bucket (defaults to env INFLUXDB_BUCKET)
            influx_org: InfluxDB organization (defaults to "None")
        """
        load_dotenv()

        self.influx_host = influx_host or os.getenv("INFLUXDB_HOST", "192.168.178.114")
        self.influx_port = influx_port or os.getenv("INFLUXDB_PORT", "8088")
        self.influx_url = f"http://{self.influx_host}:{self.influx_port}"
        self.influx_token = influx_token or os.getenv("INFLUXDB_TOKEN")
        self.influx_org = influx_org
        self.influx_bucket = influx_bucket or os.getenv("INFLUXDB_BUCKET", "power_consumption")

        # Batch accumulator
        self.batch: List[Point] = []

        # Connection pool (lazy initialized)
        self._client: Optional[InfluxDBClient] = None

    @contextmanager
    def _get_client(self):
        """Context manager for InfluxDB client with automatic cleanup"""
        client = None
        try:
            client = InfluxDBClient(
                url=self.influx_url,
                token=self.influx_token,
                org=self.influx_org
            )
            yield client
        finally:
            if client:
                client.close()

    def add_power_measurement(
        self,
        device_name: str,
        power_value: float,
        timestamp: Optional[datetime] = None,
        device_group: Optional[str] = None
    ) -> None:
        """
        Add a power measurement to the batch queue.

        Args:
            device_name: Name/identifier of the device
            power_value: Current power consumption in watts
            timestamp: Measurement timestamp (defaults to now)
            device_group: Group name for aggregation (e.g., "office" for office+office2)
                         If None, no device_group tag will be added
        """
        point = Point("power_consumption") \
            .tag("device", device_name) \
            .field("power", power_value)

        # Add optional device_group tag for Grafana aggregation
        if device_group:
            point = point.tag("device_group", device_group)

        if timestamp:
            point = point.time(timestamp, WritePrecision.NS)

        self.batch.append(point)
        logger.debug(f"Added to batch: {device_name} = {power_value}W (batch size: {len(self.batch)})")

    def add_custom_measurement(
        self,
        measurement: str,
        tags: Dict[str, str],
        fields: Dict[str, float],
        timestamp: Optional[datetime] = None
    ) -> None:
        """
        Add a custom measurement to the batch queue.

        Args:
            measurement: Measurement name (e.g., "power_consumption", "energy_daily")
            tags: Dictionary of tags (indexed fields)
            fields: Dictionary of fields (values)
            timestamp: Measurement timestamp (defaults to now)
        """
        point = Point(measurement)

        for tag_key, tag_value in tags.items():
            point = point.tag(tag_key, tag_value)

        for field_key, field_value in fields.items():
            point = point.field(field_key, field_value)

        if timestamp:
            point = point.time(timestamp, WritePrecision.NS)

        self.batch.append(point)
        logger.debug(f"Added custom measurement to batch: {measurement} (batch size: {len(self.batch)})")

    async def flush(self) -> bool:
        """
        Write all accumulated data points to InfluxDB in a single batch operation.

        Returns:
            True if successful, False otherwise
        """
        if not self.batch:
            logger.debug("No data points to flush")
            return True

        batch_size = len(self.batch)

        try:
            with self._get_client() as influx_client:
                write_api = influx_client.write_api(write_options=SYNCHRONOUS)
                write_api.write(
                    bucket=self.influx_bucket,
                    org=self.influx_org,
                    record=self.batch
                )

            logger.info(f"📊 Flushed {batch_size} data points to InfluxDB in single batch")
            self.batch.clear()
            return True

        except Exception as e:
            logger.error(f"Failed to flush batch ({batch_size} points) to InfluxDB: {e}")
            # Don't clear batch on error - allows retry
            return False

    def clear(self) -> None:
        """Clear the batch queue without writing (use after permanent failures)"""
        cleared_count = len(self.batch)
        self.batch.clear()
        if cleared_count > 0:
            logger.warning(f"Cleared {cleared_count} unsent data points from batch")

    def batch_size(self) -> int:
        """Return the current number of accumulated data points"""
        return len(self.batch)

    async def write_power_data(self, device_name: str, power_value: float) -> None:
        """
        Backward-compatible single-write method (creates batch of 1).
        For optimal performance, use add_power_measurement() + flush() instead.

        Args:
            device_name: Name/identifier of the device
            power_value: Current power consumption in watts
        """
        self.add_power_measurement(device_name, power_value)
        await self.flush()
        logger.info(f"📊 {device_name}: {power_value}W → InfluxDB (single write)")


class InfluxConnectionPool:
    """
    Connection pool for reusing InfluxDB clients across multiple operations.
    Reduces connection overhead for services that need persistent connections.
    """

    def __init__(
        self,
        influx_host: Optional[str] = None,
        influx_port: Optional[str] = None,
        influx_token: Optional[str] = None,
        influx_org: str = "None"
    ):
        """
        Initialize connection pool.

        Args:
            influx_host: InfluxDB host (defaults to env INFLUXDB_HOST)
            influx_port: InfluxDB port (defaults to env INFLUXDB_PORT)
            influx_token: InfluxDB token (defaults to env INFLUXDB_TOKEN)
            influx_org: InfluxDB organization (defaults to "None")
        """
        load_dotenv()

        self.influx_host = influx_host or os.getenv("INFLUXDB_HOST", "192.168.178.114")
        self.influx_port = influx_port or os.getenv("INFLUXDB_PORT", "8088")
        self.influx_url = f"http://{self.influx_host}:{self.influx_port}"
        self.influx_token = influx_token or os.getenv("INFLUXDB_TOKEN")
        self.influx_org = influx_org

        self._client: Optional[InfluxDBClient] = None

    def get_client(self) -> InfluxDBClient:
        """
        Get or create a persistent InfluxDB client.

        Returns:
            InfluxDBClient instance
        """
        if self._client is None:
            self._client = InfluxDBClient(
                url=self.influx_url,
                token=self.influx_token,
                org=self.influx_org
            )
            logger.info("Created new InfluxDB connection in pool")

        return self._client

    def close(self) -> None:
        """Close the persistent client connection"""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Closed InfluxDB connection pool")

    def __enter__(self):
        """Context manager entry"""
        return self.get_client()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
