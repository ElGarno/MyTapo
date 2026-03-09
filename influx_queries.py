"""
Shared InfluxDB query module for MyTapo.

Provides reusable query functions for consumption data, event data, and solar data.
Used by report_api.py and can replace inline queries in consumption_reporter.py
and event_detector.py over time.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

load_dotenv()

logger = logging.getLogger(__name__)


class InfluxQueries:
    """Shared InfluxDB query interface for all report types."""

    def __init__(self):
        self.influx_host = os.getenv("INFLUXDB_HOST", "192.168.178.114")
        self.influx_port = os.getenv("INFLUXDB_PORT", "8088")
        self.influx_url = f"http://{self.influx_host}:{self.influx_port}"
        self.influx_token = os.getenv("INFLUXDB_TOKEN")
        self.influx_org = "None"
        self.power_bucket = os.getenv("INFLUXDB_BUCKET", "power_consumption")
        self.events_bucket = os.getenv("INFLUXDB_EVENTS_BUCKET", "appliance_events")
        self.consumption_bucket = os.getenv("INFLUXDB_CONSUMPTION_BUCKET", "consumption_daily")
        self.cost_per_kwh = 0.28
        self.exclude_devices = {"solar"}

    def _get_client(self) -> InfluxDBClient:
        return InfluxDBClient(
            url=self.influx_url,
            token=self.influx_token,
            org=self.influx_org
        )

    def query_consumption_for_period(
        self, start: datetime, end: datetime
    ) -> Dict[str, float]:
        """Query total energy consumption (kWh) per device for a time period."""
        start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        hours = (end - start).total_seconds() / 3600

        query = f'''
        from(bucket: "{self.power_bucket}")
            |> range(start: {start_str}, stop: {end_str})
            |> filter(fn: (r) => r["_measurement"] == "power_consumption")
            |> filter(fn: (r) => r["_field"] == "power")
            |> group(columns: ["device"])
            |> mean()
        '''

        consumption = {}
        try:
            with self._get_client() as client:
                tables = client.query_api().query(query)
                for table in tables:
                    for record in table.records:
                        device = record.values.get("device", "unknown")
                        mean_power = record.get_value() or 0
                        kwh = (mean_power * hours) / 1000
                        if device not in self.exclude_devices:
                            consumption[device] = round(kwh, 3)
        except Exception as e:
            logger.error(f"Failed to query consumption data: {e}")

        return consumption

    def query_today_consumption(self) -> Dict[str, float]:
        """Get today's consumption so far."""
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.query_consumption_for_period(today_start, now)

    def query_events(self, days: int) -> Dict[str, Dict[str, Any]]:
        """
        Query event counts and total durations from InfluxDB.

        Returns dict mapping event_type to {count, total_duration_seconds, total_energy_wh}.
        """
        results: Dict[str, Dict[str, Any]] = {}

        # Query duration
        duration_query = f'''
        from(bucket: "{self.events_bucket}")
            |> range(start: -{days}d)
            |> filter(fn: (r) => r["_measurement"] == "event")
            |> filter(fn: (r) => r["_field"] == "duration_seconds")
            |> group(columns: ["event_type"])
        '''

        # Query energy
        energy_query = f'''
        from(bucket: "{self.events_bucket}")
            |> range(start: -{days}d)
            |> filter(fn: (r) => r["_measurement"] == "event")
            |> filter(fn: (r) => r["_field"] == "energy_wh")
            |> group(columns: ["event_type"])
        '''

        try:
            with self._get_client() as client:
                query_api = client.query_api()

                # Process duration data
                tables = query_api.query(duration_query)
                for table in tables:
                    event_type = None
                    count = 0
                    total_duration = 0.0
                    for record in table.records:
                        event_type = record.values.get("event_type")
                        count += 1
                        total_duration += record.get_value() or 0
                    if event_type:
                        results[event_type] = {
                            "count": count,
                            "total_duration_seconds": total_duration,
                            "total_energy_wh": 0.0
                        }

                # Process energy data
                tables = query_api.query(energy_query)
                for table in tables:
                    event_type = None
                    total_energy = 0.0
                    for record in table.records:
                        event_type = record.values.get("event_type")
                        total_energy += record.get_value() or 0
                    if event_type and event_type in results:
                        results[event_type]["total_energy_wh"] = total_energy

        except Exception as e:
            logger.error(f"Failed to query events: {e}")

        return results

    def query_top_devices(self, days: int = 1) -> List[Dict[str, Any]]:
        """Query top power consumers for a period, sorted by kWh descending."""
        now = datetime.utcnow()
        start = now - timedelta(days=days)
        consumption = self.query_consumption_for_period(start, now)

        sorted_devices = sorted(consumption.items(), key=lambda x: x[1], reverse=True)
        total = sum(consumption.values())

        return [
            {
                "device": device,
                "kwh": kwh,
                "percentage": round((kwh / total) * 100, 1) if total > 0 else 0,
                "cost": round(kwh * self.cost_per_kwh, 2)
            }
            for device, kwh in sorted_devices
        ]

    def query_solar_summary(self) -> Dict[str, Any]:
        """Query solar generation data from power_consumption bucket."""
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        hours_today = (now - today_start).total_seconds() / 3600

        # Today's solar (from power_consumption, device=solar)
        query_today = f'''
        from(bucket: "{self.power_bucket}")
            |> range(start: {today_start.strftime("%Y-%m-%dT%H:%M:%SZ")}, stop: {now.strftime("%Y-%m-%dT%H:%M:%SZ")})
            |> filter(fn: (r) => r["_measurement"] == "power_consumption")
            |> filter(fn: (r) => r["_field"] == "power")
            |> filter(fn: (r) => r["device"] == "solar")
            |> mean()
        '''

        # Last 7 days solar
        week_start = now - timedelta(days=7)
        query_week = f'''
        from(bucket: "{self.power_bucket}")
            |> range(start: {week_start.strftime("%Y-%m-%dT%H:%M:%SZ")}, stop: {now.strftime("%Y-%m-%dT%H:%M:%SZ")})
            |> filter(fn: (r) => r["_measurement"] == "power_consumption")
            |> filter(fn: (r) => r["_field"] == "power")
            |> filter(fn: (r) => r["device"] == "solar")
            |> mean()
        '''

        result = {
            "today_kwh": 0.0,
            "today_savings": 0.0,
            "week_kwh": 0.0,
            "week_savings": 0.0
        }

        try:
            with self._get_client() as client:
                query_api = client.query_api()

                tables = query_api.query(query_today)
                for table in tables:
                    for record in table.records:
                        mean_power = record.get_value() or 0
                        kwh = (mean_power * hours_today) / 1000
                        result["today_kwh"] = round(kwh, 3)
                        result["today_savings"] = round(kwh * self.cost_per_kwh, 2)

                hours_week = (now - week_start).total_seconds() / 3600
                tables = query_api.query(query_week)
                for table in tables:
                    for record in table.records:
                        mean_power = record.get_value() or 0
                        kwh = (mean_power * hours_week) / 1000
                        result["week_kwh"] = round(kwh, 3)
                        result["week_savings"] = round(kwh * self.cost_per_kwh, 2)

        except Exception as e:
            logger.error(f"Failed to query solar data: {e}")

        return result

    def query_comparison(self, period: str = "week") -> Dict[str, Any]:
        """Compare current period vs previous period."""
        now = datetime.utcnow()

        if period == "day":
            current_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            prev_start = current_start - timedelta(days=1)
            prev_end = current_start
        elif period == "week":
            current_start = now - timedelta(days=7)
            prev_start = current_start - timedelta(days=7)
            prev_end = current_start
        elif period == "month":
            current_start = now - timedelta(days=30)
            prev_start = current_start - timedelta(days=30)
            prev_end = current_start
        else:
            current_start = now - timedelta(days=7)
            prev_start = current_start - timedelta(days=7)
            prev_end = current_start

        current = self.query_consumption_for_period(current_start, now)
        previous = self.query_consumption_for_period(prev_start, prev_end)

        current_total = sum(current.values())
        previous_total = sum(previous.values())

        if previous_total > 0:
            change_pct = ((current_total - previous_total) / previous_total) * 100
        else:
            change_pct = 0.0

        # Current events
        days_map = {"day": 1, "week": 7, "month": 30}
        days = days_map.get(period, 7)
        current_events = self.query_events(days)
        previous_events = self.query_events(days * 2)

        return {
            "period": period,
            "current": {
                "total_kwh": round(current_total, 2),
                "cost": round(current_total * self.cost_per_kwh, 2),
                "devices": current,
                "events": current_events
            },
            "previous": {
                "total_kwh": round(previous_total, 2),
                "cost": round(previous_total * self.cost_per_kwh, 2),
                "devices": previous,
                "events": previous_events
            },
            "change_percent": round(change_pct, 1),
            "trend": f"+{change_pct:.0f}%" if change_pct > 0 else f"{change_pct:.0f}%"
        }

    def query_custom_context(self, question: str = "") -> Dict[str, Any]:
        """
        Build a data context for AI analysis.

        Returns a summary of recent data that can be passed to Claude API.
        """
        today = self.query_today_consumption()
        top_devices = self.query_top_devices(days=1)
        events_today = self.query_events(1)
        events_week = self.query_events(7)
        solar = self.query_solar_summary()
        comparison = self.query_comparison("week")

        return {
            "question": question,
            "today_consumption": {
                "total_kwh": round(sum(today.values()), 2),
                "cost": round(sum(today.values()) * self.cost_per_kwh, 2),
                "devices": today
            },
            "top_devices_today": top_devices[:5],
            "events_today": events_today,
            "events_week": events_week,
            "solar": solar,
            "weekly_comparison": comparison
        }
