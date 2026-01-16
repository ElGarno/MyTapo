"""
Consumption Reporter for MyTapo.

Generates periodic energy consumption reports with device breakdowns,
charts, and cost calculations. Sends reports via Pushover (with charts)
and displays summaries on AWTRIX display.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from io import BytesIO
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server
import matplotlib.pyplot as plt

from utils import send_pushover_notification_with_image, get_awtrix_client
from awtrix_client import AwtrixMessage

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ConsumptionData:
    """Container for consumption data."""
    device: str
    kwh: float
    percentage: float
    cost: float


class ConsumptionReporter:
    """Main service for generating and sending consumption reports."""

    def __init__(self):
        # InfluxDB configuration
        self.influx_host = os.getenv("INFLUXDB_HOST", "192.168.178.114")
        self.influx_port = os.getenv("INFLUXDB_PORT", "8088")
        self.influx_url = f"http://{self.influx_host}:{self.influx_port}"
        self.influx_token = os.getenv("INFLUXDB_TOKEN")
        self.influx_org = "None"
        self.influx_bucket = os.getenv("INFLUXDB_BUCKET", "power_consumption")
        self.consumption_bucket = os.getenv("INFLUXDB_CONSUMPTION_BUCKET", "consumption_daily")

        # Pushover configuration
        self.pushover_user = os.getenv("PUSHOVER_USER_GROUP_WOERIS")

        # AWTRIX client
        self.awtrix_client = get_awtrix_client()

        # Cost configuration
        self.cost_per_kwh = 0.28
        self.currency_symbol = "EUR"

        # Report settings
        self.config = self._load_config()

        # Tracking for scheduling
        self.last_weekly = None
        self.last_monthly = None
        self.last_yearly = None
        self.last_awtrix_carousel = None
        self.last_daily_storage = None

        # Devices to exclude from reports (e.g., solar is generation, not consumption)
        self.exclude_devices = {"solar"}

    def _load_config(self) -> dict:
        """Load configuration from appliance_profiles.json."""
        config_path = os.path.join(
            os.path.dirname(__file__),
            "config",
            "appliance_profiles.json"
        )
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config.get("settings", {}).get("consumption_reports", {})
        except Exception as e:
            logger.warning(f"Could not load config: {e}, using defaults")
            return {}

    def _get_client(self) -> InfluxDBClient:
        """Create InfluxDB client."""
        return InfluxDBClient(
            url=self.influx_url,
            token=self.influx_token,
            org=self.influx_org
        )

    async def query_consumption_for_period(
        self,
        start: datetime,
        end: datetime
    ) -> Dict[str, float]:
        """
        Query total energy consumption (kWh) per device for a time period.

        Uses mean power × hours to calculate energy.
        """
        start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        hours = (end - start).total_seconds() / 3600

        query = f'''
        from(bucket: "{self.influx_bucket}")
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
                        # Energy (kWh) = mean power (W) × hours / 1000
                        kwh = (mean_power * hours) / 1000
                        if device not in self.exclude_devices:
                            consumption[device] = kwh
        except Exception as e:
            logger.error(f"Failed to query consumption data: {e}")

        return consumption

    async def query_today_consumption(self) -> Dict[str, float]:
        """Get today's consumption so far for AWTRIX display."""
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.query_consumption_for_period(today_start, now)

    async def query_peak_hours(
        self,
        start: datetime,
        end: datetime,
        top_n: int = 3
    ) -> List[Tuple[int, float]]:
        """
        Get peak consumption hours.

        Returns list of (hour, avg_power_watts) tuples.
        """
        start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        query = f'''
        import "date"

        from(bucket: "{self.influx_bucket}")
            |> range(start: {start_str}, stop: {end_str})
            |> filter(fn: (r) => r["_measurement"] == "power_consumption")
            |> filter(fn: (r) => r["_field"] == "power")
            |> map(fn: (r) => ({{r with hour: date.hour(t: r._time)}}))
            |> group(columns: ["hour"])
            |> mean()
            |> sort(columns: ["_value"], desc: true)
            |> limit(n: {top_n})
        '''

        peak_hours = []
        try:
            with self._get_client() as client:
                tables = client.query_api().query(query)
                for table in tables:
                    for record in table.records:
                        hour = record.values.get("hour", 0)
                        power = record.get_value() or 0
                        peak_hours.append((hour, power))
        except Exception as e:
            logger.error(f"Failed to query peak hours: {e}")

        return peak_hours

    def calculate_device_breakdown(
        self,
        consumption: Dict[str, float]
    ) -> List[ConsumptionData]:
        """Calculate consumption breakdown with percentages and costs."""
        total = sum(consumption.values())
        if total == 0:
            return []

        breakdown = []
        for device, kwh in sorted(consumption.items(), key=lambda x: x[1], reverse=True):
            percentage = (kwh / total) * 100
            cost = kwh * self.cost_per_kwh
            breakdown.append(ConsumptionData(
                device=device,
                kwh=kwh,
                percentage=percentage,
                cost=cost
            ))

        return breakdown

    def calculate_comparison(
        self,
        current: float,
        previous: float
    ) -> Tuple[float, str]:
        """Calculate percentage change and trend indicator."""
        if previous == 0:
            return 0.0, "N/A"

        change = ((current - previous) / previous) * 100
        if change > 0:
            trend = f"+{change:.0f}%"
        else:
            trend = f"{change:.0f}%"

        return change, trend

    def generate_pie_chart(
        self,
        consumption: Dict[str, float],
        title: str
    ) -> bytes:
        """Generate a pie chart showing device consumption breakdown."""
        if not consumption:
            return b""

        # Sort by consumption and take top 5 + others
        sorted_items = sorted(consumption.items(), key=lambda x: x[1], reverse=True)
        top_items = sorted_items[:5]
        others_sum = sum(v for k, v in sorted_items[5:])

        labels = []
        values = []
        for device, kwh in top_items:
            labels.append(f"{device}\n{kwh:.1f}kWh")
            values.append(kwh)

        if others_sum > 0:
            labels.append(f"Others\n{others_sum:.1f}kWh")
            values.append(others_sum)

        # Create figure
        fig, ax = plt.subplots(figsize=(8, 6))

        # Custom colors
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD']

        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            autopct='%1.0f%%',
            colors=colors[:len(values)],
            startangle=90,
            pctdistance=0.75
        )

        # Style the percentage labels
        for autotext in autotexts:
            autotext.set_fontsize(10)
            autotext.set_fontweight('bold')

        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

        # Save to bytes
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        buf.seek(0)
        plt.close(fig)

        return buf.read()

    def format_pushover_report(
        self,
        period_name: str,
        date_range: str,
        total_kwh: float,
        cost: float,
        breakdown: List[ConsumptionData],
        comparison: Optional[Tuple[float, str]] = None,
        peak_hours: Optional[List[Tuple[int, float]]] = None
    ) -> str:
        """Format the Pushover notification message."""
        lines = [
            f"{period_name} Energy Report ({date_range})",
            "",
            f"Total: {total_kwh:.1f} kWh | {self.currency_symbol}{cost:.2f}"
        ]

        if comparison and comparison[1] != "N/A":
            lines.append(f"Trend: {comparison[1]} vs previous period")

        lines.append("")
        lines.append("Top Consumers:")

        for i, item in enumerate(breakdown[:3], 1):
            lines.append(
                f"{i}. {item.device}: {item.kwh:.1f} kWh ({item.percentage:.0f}%) - "
                f"{self.currency_symbol}{item.cost:.2f}"
            )

        if peak_hours:
            lines.append("")
            hours_str = ", ".join(f"{h}:00" for h, _ in peak_hours[:3])
            lines.append(f"Peak Hours: {hours_str}")

        return "\n".join(lines)

    async def send_pushover_report(
        self,
        message: str,
        chart_png: bytes,
        title: str = "Energy Report"
    ) -> bool:
        """Send Pushover notification with chart attachment."""
        if not self.pushover_user:
            logger.error("PUSHOVER_USER_GROUP_WOERIS not configured")
            return False

        return send_pushover_notification_with_image(
            user=self.pushover_user,
            message=message,
            image_data=chart_png,
            title=title
        )

    async def send_awtrix_consumption(
        self,
        total_kwh: float,
        cost: float,
        top_devices: List[ConsumptionData]
    ) -> None:
        """Send consumption data to AWTRIX display."""
        if not self.awtrix_client:
            logger.warning("AWTRIX client not available")
            return

        # Main consumption message
        top_device = top_devices[0] if top_devices else None
        top_str = f" | Top: {top_device.device} {top_device.percentage:.0f}%" if top_device else ""

        message = AwtrixMessage(
            text=f"Today: {total_kwh:.1f}kWh {self.currency_symbol}{cost:.2f}{top_str}",
            icon="2709",  # Lightning bolt / energy icon
            color="#00BFFF",  # Deep sky blue
            duration=10
        )

        success = self.awtrix_client.send_notification(message)
        if success:
            logger.info(f"AWTRIX consumption display sent: {total_kwh:.1f}kWh")
        else:
            logger.error("Failed to send AWTRIX consumption display")

    async def run_weekly_report(self) -> None:
        """Generate and send weekly report (Sunday evening)."""
        logger.info("Generating weekly consumption report...")

        now = datetime.utcnow()
        end = now
        start = now - timedelta(days=7)
        prev_start = start - timedelta(days=7)
        prev_end = start

        # Query current and previous period
        current_consumption = await self.query_consumption_for_period(start, end)
        previous_consumption = await self.query_consumption_for_period(prev_start, prev_end)
        peak_hours = await self.query_peak_hours(start, end)

        current_total = sum(current_consumption.values())
        previous_total = sum(previous_consumption.values())
        cost = current_total * self.cost_per_kwh

        breakdown = self.calculate_device_breakdown(current_consumption)
        comparison = self.calculate_comparison(current_total, previous_total)

        # Format date range
        date_range = f"{start.strftime('%b %d')} - {end.strftime('%b %d')}"

        # Generate chart and message
        chart = self.generate_pie_chart(current_consumption, f"Weekly Consumption\n{date_range}")
        message = self.format_pushover_report(
            "Weekly", date_range, current_total, cost, breakdown, comparison, peak_hours
        )

        # Send report
        success = await self.send_pushover_report(message, chart, "Weekly Energy Report")
        if success:
            logger.info("Weekly report sent successfully")
        else:
            logger.error("Failed to send weekly report")

    async def run_monthly_report(self) -> None:
        """Generate and send monthly report (1st of month)."""
        logger.info("Generating monthly consumption report...")

        now = datetime.utcnow()
        # Last month
        end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = (end - timedelta(days=1)).replace(day=1)
        # Previous month
        prev_end = start
        prev_start = (prev_end - timedelta(days=1)).replace(day=1)

        current_consumption = await self.query_consumption_for_period(start, end)
        previous_consumption = await self.query_consumption_for_period(prev_start, prev_end)
        peak_hours = await self.query_peak_hours(start, end)

        current_total = sum(current_consumption.values())
        previous_total = sum(previous_consumption.values())
        cost = current_total * self.cost_per_kwh

        breakdown = self.calculate_device_breakdown(current_consumption)
        comparison = self.calculate_comparison(current_total, previous_total)

        month_name = start.strftime("%B %Y")

        chart = self.generate_pie_chart(current_consumption, f"Monthly Consumption\n{month_name}")
        message = self.format_pushover_report(
            "Monthly", month_name, current_total, cost, breakdown, comparison, peak_hours
        )

        success = await self.send_pushover_report(message, chart, "Monthly Energy Report")
        if success:
            logger.info("Monthly report sent successfully")
        else:
            logger.error("Failed to send monthly report")

    async def run_yearly_report(self) -> None:
        """Generate and send yearly report (January 1st)."""
        logger.info("Generating yearly consumption report...")

        now = datetime.utcnow()
        # Last year
        end = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        start = end.replace(year=end.year - 1)
        # Previous year
        prev_end = start
        prev_start = prev_end.replace(year=prev_end.year - 1)

        current_consumption = await self.query_consumption_for_period(start, end)
        previous_consumption = await self.query_consumption_for_period(prev_start, prev_end)
        peak_hours = await self.query_peak_hours(start, end, top_n=5)

        current_total = sum(current_consumption.values())
        previous_total = sum(previous_consumption.values())
        cost = current_total * self.cost_per_kwh

        breakdown = self.calculate_device_breakdown(current_consumption)
        comparison = self.calculate_comparison(current_total, previous_total)

        year_str = str(start.year)

        chart = self.generate_pie_chart(current_consumption, f"Yearly Consumption\n{year_str}")
        message = self.format_pushover_report(
            "Yearly", year_str, current_total, cost, breakdown, comparison, peak_hours
        )

        success = await self.send_pushover_report(message, chart, "Yearly Energy Report")
        if success:
            logger.info("Yearly report sent successfully")
        else:
            logger.error("Failed to send yearly report")

    async def run_awtrix_carousel(self) -> None:
        """Send today's consumption to AWTRIX carousel."""
        logger.info("Sending consumption to AWTRIX carousel...")

        consumption = await self.query_today_consumption()
        total_kwh = sum(consumption.values())
        cost = total_kwh * self.cost_per_kwh
        breakdown = self.calculate_device_breakdown(consumption)

        await self.send_awtrix_consumption(total_kwh, cost, breakdown)

    async def store_daily_consumption(self, date: Optional[datetime] = None) -> bool:
        """
        Store daily consumption summary to InfluxDB.

        Calculates and stores per-device consumption for the specified day
        (or yesterday if not specified) to the consumption_daily bucket.

        Args:
            date: The date to store consumption for (defaults to yesterday)

        Returns:
            bool: True if successful, False otherwise
        """
        if date is None:
            # Default to yesterday (complete day)
            date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        date_str = start.strftime("%Y-%m-%d")

        logger.info(f"Storing daily consumption for {date_str}...")

        # Query consumption for the day
        consumption = await self.query_consumption_for_period(start, end)

        if not consumption:
            logger.warning(f"No consumption data found for {date_str}")
            return False

        total_kwh = sum(consumption.values())
        breakdown = self.calculate_device_breakdown(consumption)

        try:
            with self._get_client() as client:
                write_api = client.write_api(write_options=SYNCHRONOUS)

                # Store per-device consumption
                for item in breakdown:
                    point = Point("daily_consumption") \
                        .tag("device", item.device) \
                        .field("kwh", item.kwh) \
                        .field("cost", item.cost) \
                        .field("percentage", item.percentage) \
                        .time(start, WritePrecision.NS)

                    write_api.write(
                        bucket=self.consumption_bucket,
                        org=self.influx_org,
                        record=point
                    )

                # Store total consumption for the day
                total_point = Point("daily_consumption") \
                    .tag("device", "_total") \
                    .field("kwh", total_kwh) \
                    .field("cost", total_kwh * self.cost_per_kwh) \
                    .field("percentage", 100.0) \
                    .time(start, WritePrecision.NS)

                write_api.write(
                    bucket=self.consumption_bucket,
                    org=self.influx_org,
                    record=total_point
                )

            logger.info(f"Stored daily consumption for {date_str}: {total_kwh:.2f} kWh "
                       f"({len(breakdown)} devices)")
            return True

        except Exception as e:
            logger.error(f"Failed to store daily consumption: {e}")
            return False

    async def backfill_daily_consumption(self, days: int = 30) -> None:
        """
        Backfill daily consumption data for the specified number of days.

        Useful for populating historical data when first deploying.

        Args:
            days: Number of days to backfill (default: 30)
        """
        logger.info(f"Backfilling daily consumption for {days} days...")

        now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        success_count = 0
        fail_count = 0

        for i in range(1, days + 1):
            date = now - timedelta(days=i)
            if await self.store_daily_consumption(date):
                success_count += 1
            else:
                fail_count += 1

        logger.info(f"Backfill complete: {success_count} days stored, {fail_count} failed")

    async def run(self) -> None:
        """Main service loop with scheduling."""
        logger.info("=" * 60)
        logger.info("Consumption Reporter Service Started")
        logger.info("=" * 60)
        logger.info(f"InfluxDB: {self.influx_url}")
        logger.info(f"Consumption bucket: {self.consumption_bucket}")
        logger.info(f"Cost rate: {self.currency_symbol}{self.cost_per_kwh}/kWh")

        polling_interval = 60  # Check every minute

        while True:
            try:
                now = datetime.now()

                # Daily consumption storage: 00:05 every day (store yesterday's data)
                if (now.hour == 0 and now.minute == 5
                    and (self.last_daily_storage is None or self.last_daily_storage.date() != now.date())):
                    await self.store_daily_consumption()
                    self.last_daily_storage = now

                # Weekly report: Sunday (weekday=6) at 20:05
                if (now.weekday() == 6 and now.hour == 20 and now.minute == 5
                    and (self.last_weekly is None or self.last_weekly.date() != now.date())):
                    await self.run_weekly_report()
                    self.last_weekly = now

                # Monthly report: 1st of month at 20:05
                if (now.day == 1 and now.hour == 20 and now.minute == 5
                    and (self.last_monthly is None or self.last_monthly.month != now.month)):
                    await self.run_monthly_report()
                    self.last_monthly = now

                # Yearly report: January 1st at 20:05
                if (now.month == 1 and now.day == 1 and now.hour == 20 and now.minute == 5
                    and (self.last_yearly is None or self.last_yearly.year != now.year)):
                    await self.run_yearly_report()
                    self.last_yearly = now

                # AWTRIX carousel: every 20 minutes at xx:15, xx:35, xx:55
                # (offset from event_detector summaries at xx:05, xx:25, xx:45)
                if now.minute in (15, 35, 55):
                    if (self.last_awtrix_carousel is None or
                        (now - self.last_awtrix_carousel).total_seconds() >= 1200):
                        await self.run_awtrix_carousel()
                        self.last_awtrix_carousel = now

            except Exception as e:
                logger.error(f"Error in main loop: {e}")

            await asyncio.sleep(polling_interval)


async def test_report():
    """Test function to generate a report immediately."""
    reporter = ConsumptionReporter()

    logger.info("Testing weekly report generation...")

    now = datetime.utcnow()
    start = now - timedelta(days=7)

    consumption = await reporter.query_consumption_for_period(start, now)
    logger.info(f"Consumption data: {consumption}")

    if consumption:
        total = sum(consumption.values())
        breakdown = reporter.calculate_device_breakdown(consumption)

        logger.info(f"Total: {total:.2f} kWh")
        for item in breakdown[:5]:
            logger.info(f"  {item.device}: {item.kwh:.2f} kWh ({item.percentage:.1f}%)")

        # Generate chart
        chart = reporter.generate_pie_chart(consumption, "Test Chart")
        logger.info(f"Chart generated: {len(chart)} bytes")

        # Send AWTRIX test
        await reporter.run_awtrix_carousel()
    else:
        logger.warning("No consumption data found")


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Consumption Reporter Service")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run test report generation"
    )
    parser.add_argument(
        "--backfill",
        type=int,
        metavar="DAYS",
        help="Backfill daily consumption data for specified number of days"
    )
    args = parser.parse_args()

    if args.test:
        asyncio.run(test_report())
    elif args.backfill:
        reporter = ConsumptionReporter()
        asyncio.run(reporter.backfill_daily_consumption(args.backfill))
    else:
        reporter = ConsumptionReporter()
        asyncio.run(reporter.run())


if __name__ == "__main__":
    main()
