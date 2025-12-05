"""
Appliance Event Detection Service for MyTapo.

Detects appliance usage events (espresso, TV sessions, charging, etc.) from power
consumption data and stores them in a dedicated InfluxDB bucket for analytics.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import deque
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from awtrix_client import AwtrixClient, AwtrixMessage
from utils import send_pushover_notification_new

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Represents a detected appliance event."""
    device: str
    event_type: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    energy_wh: float
    peak_power: float
    avg_power: float


@dataclass
class DetectorState:
    """Tracks the state of an appliance detector."""
    state: str = "idle"  # idle, active, cooling_down
    event_start: Optional[datetime] = None
    cooling_start: Optional[datetime] = None
    power_readings: List[tuple] = field(default_factory=list)
    last_event_end: Optional[datetime] = None


class ApplianceEventDetector:
    """Generic event detector using configurable profiles."""

    def __init__(self, device_name: str, profile: dict, settings: dict):
        self.device_name = device_name
        self.profile = profile
        self.settings = settings
        self.detector_state = DetectorState()

        logger.info(f"Initialized detector for {device_name}: {profile['event_name']} "
                   f"(on>{profile['threshold_on']}W, off<{profile['threshold_off']}W)")

    def process_reading(self, power: float, timestamp: datetime) -> Optional[Event]:
        """
        Process a power reading and return an Event if one completed.

        Args:
            power: Current power reading in watts
            timestamp: Timestamp of the reading

        Returns:
            Event object if an event completed, None otherwise
        """
        state = self.detector_state
        profile = self.profile

        # Cooldown check - prevent duplicate events
        if state.last_event_end:
            cooldown = profile.get("cooldown_seconds", 60)
            if (timestamp - state.last_event_end).total_seconds() < cooldown:
                return None

        if state.state == "idle":
            if power >= profile["threshold_on"]:
                state.state = "active"
                state.event_start = timestamp
                state.power_readings = [(power, timestamp)]
                logger.info(f"{self.device_name}: Event started (power={power:.1f}W)")

        elif state.state == "active":
            state.power_readings.append((power, timestamp))

            if power < profile["threshold_off"]:
                state.state = "cooling_down"
                state.cooling_start = timestamp
                logger.debug(f"{self.device_name}: Cooling down (power={power:.1f}W)")

        elif state.state == "cooling_down":
            if power >= profile["threshold_off"]:
                # False alarm, back to active
                state.state = "active"
                state.power_readings.append((power, timestamp))
                state.cooling_start = None
                logger.debug(f"{self.device_name}: Back to active (power={power:.1f}W)")
            else:
                # Check if cooling period elapsed
                cooling_confirmation = self.settings.get("cooling_confirmation_seconds", 30)
                cooling_duration = (timestamp - state.cooling_start).total_seconds()

                if cooling_duration >= cooling_confirmation:
                    return self._finalize_event(timestamp)

        return None

    def _finalize_event(self, end_time: datetime) -> Optional[Event]:
        """Calculate event metrics and return Event object."""
        state = self.detector_state
        profile = self.profile

        duration = (end_time - state.event_start).total_seconds()

        # Validate duration
        min_dur = profile.get("min_duration_seconds", 0)
        max_dur = profile.get("max_duration_seconds")

        if duration < min_dur:
            logger.info(f"{self.device_name}: Event too short ({duration:.0f}s < {min_dur}s), discarding")
            self._reset()
            return None

        if max_dur and duration > max_dur:
            logger.info(f"{self.device_name}: Event too long ({duration:.0f}s > {max_dur}s), discarding")
            self._reset()
            return None

        # Calculate metrics
        powers = [p for p, t in state.power_readings]
        peak_power = max(powers) if powers else 0
        avg_power = sum(powers) / len(powers) if powers else 0
        energy_wh = (avg_power * duration) / 3600

        event = Event(
            device=self.device_name,
            event_type=profile["event_name"],
            start_time=state.event_start,
            end_time=end_time,
            duration_seconds=duration,
            energy_wh=energy_wh,
            peak_power=peak_power,
            avg_power=avg_power
        )

        logger.info(f"{self.device_name}: Event completed - {profile['event_name']} "
                   f"(duration={duration:.0f}s, energy={energy_wh:.1f}Wh, peak={peak_power:.0f}W)")

        state.last_event_end = end_time
        self._reset()
        return event

    def _reset(self):
        """Reset detector state for next event."""
        self.detector_state.state = "idle"
        self.detector_state.event_start = None
        self.detector_state.cooling_start = None
        self.detector_state.power_readings = []


class EventDetectorService:
    """Main service that orchestrates event detection across all appliances."""

    def __init__(self):
        # InfluxDB configuration
        self.influx_host = os.getenv("INFLUXDB_HOST", "192.168.178.114")
        self.influx_port = os.getenv("INFLUXDB_PORT", "8088")
        self.influx_url = f"http://{self.influx_host}:{self.influx_port}"
        self.influx_token = os.getenv("INFLUXDB_TOKEN")
        self.influx_org = "None"
        self.source_bucket = os.getenv("INFLUXDB_BUCKET", "power_consumption")
        self.events_bucket = os.getenv("INFLUXDB_EVENTS_BUCKET", "appliance_events")

        # AWTRIX configuration
        self.awtrix_host = os.getenv("AWTRIX_HOST", "192.168.178.108")
        self.awtrix_port = int(os.getenv("AWTRIX_PORT", "80"))
        self.awtrix_client = AwtrixClient(self.awtrix_host, self.awtrix_port)

        # Pushover configuration
        self.pushover_user = os.getenv("PUSHOVER_USER_GROUP_WOERIS")

        # Load profiles
        self.profiles: Dict[str, dict] = {}
        self.settings: dict = {}
        self.detectors: Dict[str, ApplianceEventDetector] = {}

        # Event tracking for summaries
        self.today_events: List[Event] = []
        self.last_summary_minute: Optional[int] = None  # Track which xx:x5 minute we last ran summary
        self.last_daily_summary: Optional[datetime] = None

        # AWTRIX notification queue for messages waiting for safe window
        self.awtrix_queue: deque[AwtrixMessage] = deque()

        self._load_profiles()
        self._initialize_detectors()

    def _load_profiles(self):
        """Load appliance profiles from configuration file."""
        config_path = os.path.join(
            os.path.dirname(__file__),
            "config",
            "appliance_profiles.json"
        )

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                self.profiles = config.get("profiles", {})
                self.settings = config.get("settings", {})
                logger.info(f"Loaded {len(self.profiles)} appliance profiles")
        except FileNotFoundError:
            logger.error(f"Profile configuration not found at {config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in profile configuration: {e}")
            raise

    def _initialize_detectors(self):
        """Create detector instances for each profiled device."""
        for device_name, profile in self.profiles.items():
            self.detectors[device_name] = ApplianceEventDetector(
                device_name, profile, self.settings
            )
        logger.info(f"Initialized {len(self.detectors)} event detectors")

    def _is_carousel_window(self) -> bool:
        """
        Check if we're currently in the carousel display window.

        Carousel runs at xx:x0 (minutes 0, 10, 20, 30, 40, 50) and takes ~2 minutes.
        Safe window for event detector is xx:x3 to xx:x9 (minutes 3-9, 13-19, etc.)
        """
        current_minute = datetime.now().minute
        minute_in_cycle = current_minute % 10
        # Carousel window: minutes 0, 1, 2 of each 10-minute cycle
        return minute_in_cycle < 3

    def _is_summary_time(self) -> bool:
        """
        Check if it's time for scheduled summary (every 20 min at xx:x5).

        Summaries run at xx:05, xx:25, xx:45 - every 20 minutes.
        """
        current_minute = datetime.now().minute
        return current_minute in (5, 25, 45)

    def _queue_awtrix_message(self, message: AwtrixMessage):
        """
        Queue an AWTRIX message for sending during safe window.

        Messages are queued if currently in carousel window,
        otherwise sent immediately.
        """
        self.awtrix_queue.append(message)
        logger.debug(f"Queued AWTRIX message: {message.text}")

    def _send_awtrix_immediately(self, message: AwtrixMessage) -> bool:
        """Send an AWTRIX message immediately if in safe window."""
        if self._is_carousel_window():
            logger.debug(f"In carousel window, queueing message: {message.text}")
            self.awtrix_queue.append(message)
            return False

        try:
            self.awtrix_client.send_notification(message)
            logger.info(f"Sent AWTRIX message: {message.text}")
            return True
        except Exception as e:
            logger.error(f"Failed to send AWTRIX message: {e}")
            return False

    async def _process_awtrix_queue(self):
        """Process pending AWTRIX messages if we're in a safe window."""
        if self._is_carousel_window():
            if self.awtrix_queue:
                logger.debug(f"In carousel window, {len(self.awtrix_queue)} messages waiting")
            return

        # Safe window - send all queued messages
        while self.awtrix_queue:
            message = self.awtrix_queue.popleft()
            try:
                self.awtrix_client.send_notification(message)
                logger.info(f"Sent queued AWTRIX message: {message.text}")
            except Exception as e:
                logger.error(f"Failed to send AWTRIX message: {e}")

    def _get_influx_client(self) -> InfluxDBClient:
        """Create InfluxDB client."""
        return InfluxDBClient(
            url=self.influx_url,
            token=self.influx_token,
            org=self.influx_org
        )

    def _query_events_from_influx(self, days: int) -> Dict[str, Dict[str, Any]]:
        """
        Query event counts and durations from InfluxDB for a given time range.

        Args:
            days: Number of days to look back

        Returns:
            Dict mapping event_type to {count, total_duration_seconds}
        """
        query = f'''
        from(bucket: "{self.events_bucket}")
            |> range(start: -{days}d)
            |> filter(fn: (r) => r["_measurement"] == "event")
            |> filter(fn: (r) => r["_field"] == "duration_seconds")
            |> group(columns: ["event_type"])
        '''

        results: Dict[str, Dict[str, Any]] = {}

        try:
            with self._get_influx_client() as client:
                query_api = client.query_api()
                tables = query_api.query(query)

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
                            "total_duration_seconds": total_duration
                        }

        except Exception as e:
            logger.error(f"Failed to query events from InfluxDB: {e}")

        return results

    def _format_period_summary(self, events: Dict[str, Dict[str, Any]], period: str) -> Optional[str]:
        """
        Format a summary string for a time period.

        Args:
            events: Dict from _query_events_from_influx
            period: Period name (Day, Week, Month, Year)

        Returns:
            Formatted summary string or None if no events
        """
        if not events:
            return None

        parts = []
        tv_duration = 0

        for event_type, data in events.items():
            count = data["count"]
            duration = data["total_duration_seconds"]

            # Track TV time separately for prominent display
            if event_type == "tv_session":
                tv_duration = duration
                continue  # Will be added at the end

            # Find the profile to check if we track duration
            profile = None
            for device_profile in self.profiles.values():
                if device_profile.get("event_name") == event_type:
                    profile = device_profile
                    break

            if profile and profile.get("track_duration") and duration > 60:
                hours = duration / 3600
                if hours >= 1:
                    parts.append(f"{count} {event_type} ({hours:.0f}h)")
                else:
                    parts.append(f"{count} {event_type} ({duration/60:.0f}m)")
            else:
                parts.append(f"{count} {event_type}")

        # Add TV time prominently at the end
        if tv_duration > 0:
            tv_hours = tv_duration / 3600
            tv_minutes = (tv_duration % 3600) / 60
            if tv_hours >= 1:
                if tv_minutes >= 5:
                    parts.append(f"TV {int(tv_hours)}h{int(tv_minutes)}m")
                else:
                    parts.append(f"TV {tv_hours:.1f}h")
            else:
                parts.append(f"TV {int(tv_minutes)}m")

        if not parts:
            return None

        return f"{period}: {', '.join(parts)}"

    async def _query_latest_power(self) -> Dict[str, tuple]:
        """
        Query latest power readings for all profiled devices.

        Returns:
            Dict mapping device name to (power, timestamp) tuple
        """
        device_names = list(self.profiles.keys())
        device_filter = " or ".join([f'r["device"] == "{d}"' for d in device_names])

        query = f'''
        from(bucket: "{self.source_bucket}")
            |> range(start: -1m)
            |> filter(fn: (r) => r["_measurement"] == "power_consumption")
            |> filter(fn: (r) => r["_field"] == "power")
            |> filter(fn: (r) => {device_filter})
            |> last()
        '''

        results = {}
        try:
            with self._get_influx_client() as client:
                query_api = client.query_api()
                tables = query_api.query(query)

                for table in tables:
                    for record in table.records:
                        device = record.values.get("device")
                        power = record.get_value()
                        timestamp = record.get_time()
                        if device and power is not None:
                            results[device] = (power, timestamp)

        except Exception as e:
            logger.error(f"Failed to query power data: {e}")

        return results

    async def _write_event(self, event: Event):
        """Write detected event to InfluxDB events bucket."""
        try:
            point = Point("event") \
                .tag("device", event.device) \
                .tag("event_type", event.event_type) \
                .tag("hour_of_day", str(event.start_time.hour)) \
                .tag("day_of_week", str(event.start_time.weekday())) \
                .field("duration_seconds", event.duration_seconds) \
                .field("energy_wh", event.energy_wh) \
                .field("peak_power", event.peak_power) \
                .field("avg_power", event.avg_power) \
                .time(event.start_time, WritePrecision.NS)

            with self._get_influx_client() as client:
                write_api = client.write_api(write_options=SYNCHRONOUS)
                write_api.write(
                    bucket=self.events_bucket,
                    org=self.influx_org,
                    record=point
                )

            logger.info(f"Wrote event to InfluxDB: {event.event_type} from {event.device}")

        except Exception as e:
            logger.error(f"Failed to write event to InfluxDB: {e}")

    def _send_event_notification(self, event: Event):
        """Send AWTRIX notification for completed event (if enabled)."""
        if not self.settings.get("enable_awtrix_on_event", False):
            return

        profile = self.profiles.get(event.device, {})
        icon = profile.get("awtrix_icon", "4474")

        # Format duration nicely
        if event.duration_seconds < 60:
            duration_str = f"{event.duration_seconds:.0f}s"
        elif event.duration_seconds < 3600:
            duration_str = f"{event.duration_seconds/60:.1f}min"
        else:
            duration_str = f"{event.duration_seconds/3600:.1f}h"

        message = AwtrixMessage(
            text=f"{profile.get('event_name', event.event_type)}: {duration_str}",
            icon=icon,
            color="#00FF00",
            duration=10,
            sound="chime"
        )
        # Try to send immediately if outside carousel window, otherwise queue
        self._send_awtrix_immediately(message)

    async def _send_summary(self):
        """
        Send day/week/month/year summaries to AWTRIX every 20 minutes.

        Runs at xx:05, xx:25, xx:45 - shows all 4 time periods in sequence.
        """
        if not self.settings.get("summary_enabled", True):
            return

        now = datetime.now()
        current_minute = now.minute

        # Only run at xx:05, xx:25, xx:45 (every 20 minutes)
        if not self._is_summary_time():
            return

        # Check if we already ran this minute
        if self.last_summary_minute == current_minute:
            return

        logger.info(f"Sending period summaries at {now.strftime('%H:%M')}")

        # Define time periods: (days, label, icon, color)
        periods = [
            (1, "Day", "1543", "#87CEEB"),      # Light blue - calendar
            (7, "Week", "2103", "#90EE90"),     # Light green - clock
            (30, "Month", "51462", "#FFB347"),  # Orange - chart
            (365, "Year", "27225", "#DDA0DD"),  # Plum - star
        ]

        summary_duration = self.settings.get("summary_display_seconds", 12)
        summaries_sent = 0

        for days, label, icon, color in periods:
            events = self._query_events_from_influx(days)
            summary_text = self._format_period_summary(events, label)

            if summary_text:
                message = AwtrixMessage(
                    text=summary_text,
                    icon=icon,
                    color=color,
                    duration=summary_duration
                )
                self._send_awtrix_immediately(message)
                summaries_sent += 1
                logger.info(f"Sent {label} summary: {summary_text}")

                # Small delay between messages to ensure they queue properly
                await asyncio.sleep(0.5)

        if summaries_sent == 0:
            logger.debug("No events found for any period")

        self.last_summary_minute = current_minute

    async def _send_daily_summary(self):
        """Send daily summary to AWTRIX and Pushover at configured time (default 21:05)."""
        now = datetime.now()
        summary_hour = self.settings.get("daily_summary_hour", 21)
        summary_minute = self.settings.get("daily_summary_minute", 5)  # xx:x5 to avoid carousel

        # Check if it's time for daily summary
        if now.hour != summary_hour or now.minute != summary_minute:
            return

        # Check if we already sent today
        if self.last_daily_summary and self.last_daily_summary.date() == now.date():
            return

        if not self.today_events:
            return

        # Build summary
        event_counts: Dict[str, int] = {}
        duration_totals: Dict[str, float] = {}
        energy_totals: Dict[str, float] = {}

        for event in self.today_events:
            profile = self.profiles.get(event.device, {})
            event_name = profile.get("event_name_plural", event.event_type)

            event_counts[event_name] = event_counts.get(event_name, 0) + 1

            if profile.get("track_duration"):
                duration_totals[event_name] = duration_totals.get(event_name, 0) + event.duration_seconds

            if profile.get("track_energy"):
                energy_totals[event_name] = energy_totals.get(event_name, 0) + event.energy_wh

        # Format AWTRIX message (compact)
        parts = []
        for name, count in event_counts.items():
            if name in duration_totals and duration_totals[name] > 60:
                hours = duration_totals[name] / 3600
                parts.append(f"{name} {hours:.1f}h")
            else:
                parts.append(f"{count} {name}")

        awtrix_text = f"Today: {', '.join(parts)}"
        message = AwtrixMessage(
            text=awtrix_text,
            icon="1543",  # Calendar icon
            color="#FFD700",  # Gold
            duration=20,
            sound="chime"
        )
        self._queue_awtrix_message(message)
        logger.info(f"Queued daily AWTRIX summary: {awtrix_text}")

        # Format Pushover message (detailed)
        if self.settings.get("enable_pushover_daily", True) and self.pushover_user:
            pushover_lines = ["Daily Appliance Summary:"]
            for name, count in event_counts.items():
                line = f"- {count}x {name}"
                if name in duration_totals:
                    hours = duration_totals[name] / 3600
                    line += f" ({hours:.1f}h total)"
                if name in energy_totals:
                    kwh = energy_totals[name] / 1000
                    line += f" [{kwh:.2f} kWh]"
                pushover_lines.append(line)

            pushover_text = "\n".join(pushover_lines)
            send_pushover_notification_new(self.pushover_user, pushover_text)
            logger.info("Sent daily Pushover summary")

        self.last_daily_summary = now

        # Clear today's events for tomorrow
        self.today_events = []

    async def _cleanup_old_events(self):
        """Remove events from previous days."""
        today = datetime.now().date()
        self.today_events = [
            e for e in self.today_events
            if e.start_time.date() == today
        ]

    async def run(self):
        """Main event detection loop."""
        polling_interval = self.settings.get("polling_interval_seconds", 15)

        logger.info(f"Starting event detector service (polling every {polling_interval}s)")
        logger.info(f"Source bucket: {self.source_bucket}")
        logger.info(f"Events bucket: {self.events_bucket}")
        logger.info(f"Monitoring devices: {list(self.profiles.keys())}")
        logger.info("AWTRIX schedule: Period summaries (Day/Week/Month/Year) at xx:05, xx:25, xx:45")
        logger.info("AWTRIX schedule: Carousel window avoided at xx:00-xx:02 (each 10min cycle)")

        while True:
            try:
                # Query latest power readings
                power_data = await self._query_latest_power()

                # Process each reading through corresponding detector
                for device_name, (power, timestamp) in power_data.items():
                    if device_name in self.detectors:
                        event = self.detectors[device_name].process_reading(power, timestamp)

                        if event:
                            # Store event
                            await self._write_event(event)
                            self.today_events.append(event)

                            # Send notification if enabled (immediate if safe, queued otherwise)
                            self._send_event_notification(event)

                # Check for scheduled summaries (runs at xx:x5 times)
                await self._send_summary()
                await self._send_daily_summary()
                await self._cleanup_old_events()

                # Process any queued AWTRIX messages (sent when outside carousel window)
                await self._process_awtrix_queue()

            except Exception as e:
                logger.error(f"Error in detection loop: {e}", exc_info=True)

            await asyncio.sleep(polling_interval)


async def main():
    """Entry point for the event detector service."""
    service = EventDetectorService()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
