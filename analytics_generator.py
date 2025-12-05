"""
Analytics Generator for MyTapo Appliance Events.

Generates heatmaps, duration statistics, and exports for Grafana dashboards
from the appliance_events InfluxDB bucket.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict
import csv
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AnalyticsGenerator:
    """Generates analytics and exports from appliance events data."""

    def __init__(self, output_dir: str = "analytics"):
        # InfluxDB configuration
        self.influx_host = os.getenv("INFLUXDB_HOST", "192.168.178.114")
        self.influx_port = os.getenv("INFLUXDB_PORT", "8088")
        self.influx_url = f"http://{self.influx_host}:{self.influx_port}"
        self.influx_token = os.getenv("INFLUXDB_TOKEN")
        self.influx_org = "None"
        self.events_bucket = os.getenv("INFLUXDB_EVENTS_BUCKET", "appliance_events")

        # Output directory
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"Analytics generator initialized, output dir: {output_dir}")

    def _get_influx_client(self) -> InfluxDBClient:
        """Create InfluxDB client."""
        return InfluxDBClient(
            url=self.influx_url,
            token=self.influx_token,
            org=self.influx_org
        )

    def query_events(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Query events from the last N days.

        Args:
            days: Number of days to query

        Returns:
            List of event dictionaries
        """
        query = f'''
        from(bucket: "{self.events_bucket}")
            |> range(start: -{days}d)
            |> filter(fn: (r) => r["_measurement"] == "event")
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''

        events = []
        try:
            with self._get_influx_client() as client:
                query_api = client.query_api()
                tables = query_api.query(query)

                for table in tables:
                    for record in table.records:
                        event = {
                            "timestamp": record.get_time(),
                            "device": record.values.get("device"),
                            "event_type": record.values.get("event_type"),
                            "hour_of_day": int(record.values.get("hour_of_day", 0)),
                            "day_of_week": int(record.values.get("day_of_week", 0)),
                            "duration_seconds": record.values.get("duration_seconds", 0),
                            "energy_wh": record.values.get("energy_wh", 0),
                            "peak_power": record.values.get("peak_power", 0),
                            "avg_power": record.values.get("avg_power", 0),
                        }
                        events.append(event)

            logger.info(f"Queried {len(events)} events from last {days} days")

        except Exception as e:
            logger.error(f"Failed to query events: {e}")

        return events

    def generate_heatmap_csv(self, events: List[Dict], event_type: Optional[str] = None) -> str:
        """
        Generate heatmap data (hour x day of week) as CSV.

        Args:
            events: List of event dictionaries
            event_type: Filter by event type (None = all events)

        Returns:
            Path to generated CSV file
        """
        # Filter by event type if specified
        if event_type:
            events = [e for e in events if e["event_type"] == event_type]

        # Count events by hour and day
        heatmap: Dict[tuple, int] = defaultdict(int)
        for event in events:
            key = (event["hour_of_day"], event["day_of_week"])
            heatmap[key] += 1

        # Generate CSV
        filename = f"heatmap_{event_type or 'all'}.csv"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["hour", "day_of_week", "day_name", "count"])

            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

            for hour in range(24):
                for day in range(7):
                    count = heatmap.get((hour, day), 0)
                    writer.writerow([hour, day, day_names[day], count])

        logger.info(f"Generated heatmap CSV: {filepath}")
        return filepath

    def generate_duration_stats(self, events: List[Dict]) -> Dict[str, Dict]:
        """
        Calculate duration statistics per event type.

        Args:
            events: List of event dictionaries

        Returns:
            Dictionary of statistics per event type
        """
        # Group by event type
        by_type: Dict[str, List[float]] = defaultdict(list)
        for event in events:
            if event["duration_seconds"] > 0:
                by_type[event["event_type"]].append(event["duration_seconds"])

        # Calculate statistics
        stats = {}
        for event_type, durations in by_type.items():
            if durations:
                stats[event_type] = {
                    "count": len(durations),
                    "avg_duration_seconds": sum(durations) / len(durations),
                    "min_duration_seconds": min(durations),
                    "max_duration_seconds": max(durations),
                    "total_duration_seconds": sum(durations),
                    "avg_duration_formatted": self._format_duration(sum(durations) / len(durations)),
                    "total_duration_formatted": self._format_duration(sum(durations)),
                }

        # Save to JSON
        filepath = os.path.join(self.output_dir, "duration_stats.json")
        with open(filepath, 'w') as f:
            json.dump(stats, f, indent=2)

        logger.info(f"Generated duration stats: {filepath}")
        return stats

    def generate_energy_stats(self, events: List[Dict]) -> Dict[str, Dict]:
        """
        Calculate energy consumption statistics per event type.

        Args:
            events: List of event dictionaries

        Returns:
            Dictionary of energy statistics per event type
        """
        # Group by event type
        by_type: Dict[str, List[float]] = defaultdict(list)
        for event in events:
            if event["energy_wh"] > 0:
                by_type[event["event_type"]].append(event["energy_wh"])

        # Calculate statistics
        stats = {}
        for event_type, energies in by_type.items():
            if energies:
                total_wh = sum(energies)
                stats[event_type] = {
                    "count": len(energies),
                    "avg_energy_wh": sum(energies) / len(energies),
                    "min_energy_wh": min(energies),
                    "max_energy_wh": max(energies),
                    "total_energy_wh": total_wh,
                    "total_energy_kwh": total_wh / 1000,
                    "estimated_cost_eur": (total_wh / 1000) * 0.28,  # 28 cents/kWh
                }

        # Save to JSON
        filepath = os.path.join(self.output_dir, "energy_stats.json")
        with open(filepath, 'w') as f:
            json.dump(stats, f, indent=2)

        logger.info(f"Generated energy stats: {filepath}")
        return stats

    def generate_daily_counts(self, events: List[Dict]) -> str:
        """
        Generate daily event counts as CSV for time series visualization.

        Args:
            events: List of event dictionaries

        Returns:
            Path to generated CSV file
        """
        # Count events by date and type
        by_date: Dict[tuple, int] = defaultdict(int)
        event_types = set()

        for event in events:
            date_str = event["timestamp"].strftime("%Y-%m-%d")
            event_type = event["event_type"]
            by_date[(date_str, event_type)] += 1
            event_types.add(event_type)

        # Get date range
        dates = sorted(set(k[0] for k in by_date.keys()))

        # Generate CSV
        filepath = os.path.join(self.output_dir, "daily_counts.csv")

        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            headers = ["date"] + sorted(event_types)
            writer.writerow(headers)

            for date in dates:
                row = [date]
                for event_type in sorted(event_types):
                    row.append(by_date.get((date, event_type), 0))
                writer.writerow(row)

        logger.info(f"Generated daily counts CSV: {filepath}")
        return filepath

    def generate_weekly_summary(self, events: List[Dict]) -> Dict[str, Any]:
        """
        Generate weekly summary statistics.

        Args:
            events: List of event dictionaries

        Returns:
            Summary dictionary
        """
        # Filter to last 7 days
        week_ago = datetime.now() - timedelta(days=7)
        recent = [e for e in events if e["timestamp"].replace(tzinfo=None) > week_ago]

        # Aggregate
        summary = {
            "period": "last_7_days",
            "total_events": len(recent),
            "by_type": defaultdict(lambda: {"count": 0, "total_duration_h": 0, "total_energy_kwh": 0})
        }

        for event in recent:
            et = event["event_type"]
            summary["by_type"][et]["count"] += 1
            summary["by_type"][et]["total_duration_h"] += event["duration_seconds"] / 3600
            summary["by_type"][et]["total_energy_kwh"] += event["energy_wh"] / 1000

        # Convert defaultdict to regular dict
        summary["by_type"] = dict(summary["by_type"])

        # Round values
        for et in summary["by_type"]:
            summary["by_type"][et]["total_duration_h"] = round(summary["by_type"][et]["total_duration_h"], 2)
            summary["by_type"][et]["total_energy_kwh"] = round(summary["by_type"][et]["total_energy_kwh"], 3)

        # Save to JSON
        filepath = os.path.join(self.output_dir, "weekly_summary.json")
        with open(filepath, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        logger.info(f"Generated weekly summary: {filepath}")
        return summary

    def generate_grafana_dashboard(self, event_types: List[str]) -> str:
        """
        Generate a Grafana dashboard JSON template.

        Args:
            event_types: List of event types to include

        Returns:
            Path to generated JSON file
        """
        dashboard = {
            "title": "Appliance Events Analytics",
            "uid": "appliance-events",
            "tags": ["mytapo", "events", "analytics"],
            "timezone": "browser",
            "panels": [],
            "time": {"from": "now-7d", "to": "now"},
            "refresh": "5m"
        }

        panel_id = 1

        # Add stat panels for each event type
        for i, event_type in enumerate(event_types):
            dashboard["panels"].append({
                "id": panel_id,
                "title": f"{event_type.replace('_', ' ').title()} Today",
                "type": "stat",
                "gridPos": {"x": i * 4 % 24, "y": 0, "w": 4, "h": 4},
                "targets": [{
                    "query": f'''
                    from(bucket: "appliance_events")
                      |> range(start: today())
                      |> filter(fn: (r) => r["event_type"] == "{event_type}")
                      |> count()
                    '''
                }]
            })
            panel_id += 1

        # Add heatmap panel
        dashboard["panels"].append({
            "id": panel_id,
            "title": "Events Heatmap (Hour x Day)",
            "type": "heatmap",
            "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8},
            "description": "Event frequency by hour and day of week"
        })
        panel_id += 1

        # Add time series panel
        dashboard["panels"].append({
            "id": panel_id,
            "title": "Daily Event Counts",
            "type": "timeseries",
            "gridPos": {"x": 12, "y": 4, "w": 12, "h": 8},
            "targets": [{
                "query": f'''
                from(bucket: "appliance_events")
                  |> range(start: -30d)
                  |> filter(fn: (r) => r["_measurement"] == "event")
                  |> group(columns: ["event_type"])
                  |> aggregateWindow(every: 1d, fn: count, createEmpty: false)
                '''
            }]
        })
        panel_id += 1

        # Add bar chart for durations
        dashboard["panels"].append({
            "id": panel_id,
            "title": "Average Duration by Event Type",
            "type": "barchart",
            "gridPos": {"x": 0, "y": 12, "w": 12, "h": 8},
            "description": "Average event duration in minutes"
        })

        # Save dashboard
        filepath = os.path.join(self.output_dir, "grafana_dashboard.json")
        with open(filepath, 'w') as f:
            json.dump(dashboard, f, indent=2)

        logger.info(f"Generated Grafana dashboard template: {filepath}")
        return filepath

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.1f}min"
        else:
            return f"{seconds/3600:.1f}h"

    def generate_all(self, days: int = 30):
        """
        Generate all analytics exports.

        Args:
            days: Number of days to include in analysis
        """
        logger.info(f"Generating all analytics for last {days} days...")

        # Query events
        events = self.query_events(days)

        if not events:
            logger.warning("No events found, skipping analytics generation")
            return

        # Get unique event types
        event_types = list(set(e["event_type"] for e in events))

        # Generate exports
        self.generate_heatmap_csv(events)  # All events
        for event_type in event_types:
            self.generate_heatmap_csv(events, event_type)

        self.generate_duration_stats(events)
        self.generate_energy_stats(events)
        self.generate_daily_counts(events)
        self.generate_weekly_summary(events)
        self.generate_grafana_dashboard(event_types)

        logger.info("Analytics generation complete!")


def main():
    """Entry point for standalone analytics generation."""
    generator = AnalyticsGenerator()
    generator.generate_all(days=30)


if __name__ == "__main__":
    main()
