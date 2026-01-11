"""
Backfill Historical Events for MyTapo.

One-time script that processes historical power consumption data and
detects appliance events retroactively, populating the appliance_events bucket.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class DetectorState:
    """Tracks the state of an appliance detector."""
    state: str = "idle"
    event_start: Optional[datetime] = None
    cooling_start: Optional[datetime] = None
    power_readings: List[tuple] = field(default_factory=list)
    last_event_end: Optional[datetime] = None


@dataclass
class DetectedEvent:
    """Represents a detected appliance event."""
    device: str
    event_type: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    energy_wh: float
    peak_power: float
    avg_power: float


class BackfillEventDetector:
    """Processes historical power data to detect events."""

    def __init__(self, device_name: str, profile: dict, settings: dict):
        self.device_name = device_name
        self.profile = profile
        self.settings = settings
        self.state = DetectorState()
        self.detected_events: List[DetectedEvent] = []

    def process_reading(self, power: float, timestamp: datetime):
        """Process a single power reading."""
        profile = self.profile
        state = self.state

        # Cooldown check
        if state.last_event_end:
            cooldown = profile.get("cooldown_seconds", 60)
            if (timestamp - state.last_event_end).total_seconds() < cooldown:
                return

        if state.state == "idle":
            if power >= profile["threshold_on"]:
                state.state = "active"
                state.event_start = timestamp
                state.power_readings = [(power, timestamp)]

        elif state.state == "active":
            state.power_readings.append((power, timestamp))
            if power < profile["threshold_off"]:
                state.state = "cooling_down"
                state.cooling_start = timestamp

        elif state.state == "cooling_down":
            if power >= profile["threshold_off"]:
                state.state = "active"
                state.power_readings.append((power, timestamp))
                state.cooling_start = None
            else:
                cooling_confirmation = self.settings.get("cooling_confirmation_seconds", 30)
                cooling_duration = (timestamp - state.cooling_start).total_seconds()
                if cooling_duration >= cooling_confirmation:
                    self._finalize_event(timestamp)

    def _finalize_event(self, end_time: datetime):
        """Complete an event and add it to detected events."""
        state = self.state
        profile = self.profile

        duration = (end_time - state.event_start).total_seconds()

        # Validate duration
        min_dur = profile.get("min_duration_seconds", 0)
        max_dur = profile.get("max_duration_seconds")

        if duration < min_dur or (max_dur and duration > max_dur):
            self._reset()
            return

        # Calculate metrics
        powers = [p for p, t in state.power_readings]
        peak_power = max(powers) if powers else 0
        avg_power = sum(powers) / len(powers) if powers else 0
        energy_wh = (avg_power * duration) / 3600

        event = DetectedEvent(
            device=self.device_name,
            event_type=profile["event_name"],
            start_time=state.event_start,
            end_time=end_time,
            duration_seconds=duration,
            energy_wh=energy_wh,
            peak_power=peak_power,
            avg_power=avg_power
        )
        self.detected_events.append(event)
        state.last_event_end = end_time
        self._reset()

    def _reset(self):
        """Reset detector state."""
        self.state.state = "idle"
        self.state.event_start = None
        self.state.cooling_start = None
        self.state.power_readings = []

    def finalize(self):
        """Force-close any open event at end of processing."""
        if self.state.state in ("active", "cooling_down") and self.state.event_start:
            # Use last reading timestamp as end time
            if self.state.power_readings:
                last_timestamp = self.state.power_readings[-1][1]
                self._finalize_event(last_timestamp)


class EventBackfiller:
    """Main backfill orchestrator."""

    def __init__(self, days_back: int = 365):
        # InfluxDB configuration
        self.influx_host = os.getenv("INFLUXDB_HOST", "192.168.178.114")
        self.influx_port = os.getenv("INFLUXDB_PORT", "8088")
        self.influx_url = f"http://{self.influx_host}:{self.influx_port}"
        self.influx_token = os.getenv("INFLUXDB_TOKEN")
        self.influx_org = "None"
        self.source_bucket = os.getenv("INFLUXDB_BUCKET", "power_consumption")
        self.events_bucket = os.getenv("INFLUXDB_EVENTS_BUCKET", "appliance_events")

        self.days_back = days_back
        self.profiles: Dict[str, dict] = {}
        self.settings: dict = {}
        self.detectors: Dict[str, BackfillEventDetector] = {}

        # Statistics
        self.total_events = 0
        self.events_by_type: Dict[str, int] = {}

        self._load_profiles()

    def _load_profiles(self):
        """Load appliance profiles."""
        config_path = os.path.join(
            os.path.dirname(__file__),
            "config",
            "appliance_profiles.json"
        )
        with open(config_path, 'r') as f:
            config = json.load(f)
            self.profiles = config.get("profiles", {})
            self.settings = config.get("settings", {})
        logger.info(f"Loaded {len(self.profiles)} appliance profiles")

    def _get_client(self) -> InfluxDBClient:
        """Create InfluxDB client."""
        return InfluxDBClient(
            url=self.influx_url,
            token=self.influx_token,
            org=self.influx_org
        )

    def _check_existing_events(self) -> int:
        """Check how many events already exist in the bucket."""
        query = f'''
        from(bucket: "{self.events_bucket}")
            |> range(start: -{self.days_back}d)
            |> filter(fn: (r) => r["_measurement"] == "event")
            |> count()
        '''
        try:
            with self._get_client() as client:
                tables = client.query_api().query(query)
                for table in tables:
                    for record in table.records:
                        return record.get_value() or 0
        except Exception as e:
            logger.warning(f"Could not check existing events: {e}")
        return 0

    def _query_power_data(self, device: str, start: datetime, end: datetime) -> List[tuple]:
        """Query power data for a device in a time range."""
        start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        query = f'''
        from(bucket: "{self.source_bucket}")
            |> range(start: {start_str}, stop: {end_str})
            |> filter(fn: (r) => r["_measurement"] == "power_consumption")
            |> filter(fn: (r) => r["_field"] == "power")
            |> filter(fn: (r) => r["device"] == "{device}")
            |> sort(columns: ["_time"])
        '''

        readings = []
        try:
            with self._get_client() as client:
                tables = client.query_api().query(query)
                for table in tables:
                    for record in table.records:
                        power = record.get_value()
                        timestamp = record.get_time()
                        if power is not None and timestamp:
                            # Convert to naive datetime for consistency
                            if timestamp.tzinfo:
                                timestamp = timestamp.replace(tzinfo=None)
                            readings.append((power, timestamp))
        except Exception as e:
            logger.error(f"Failed to query power data for {device}: {e}")

        return readings

    def _write_events(self, events: List[DetectedEvent]):
        """Write detected events to InfluxDB."""
        if not events:
            return

        try:
            with self._get_client() as client:
                write_api = client.write_api(write_options=SYNCHRONOUS)

                for event in events:
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

                    write_api.write(
                        bucket=self.events_bucket,
                        org=self.influx_org,
                        record=point
                    )

                    # Update statistics
                    self.total_events += 1
                    self.events_by_type[event.event_type] = \
                        self.events_by_type.get(event.event_type, 0) + 1

        except Exception as e:
            logger.error(f"Failed to write events: {e}")

    def run(self):
        """Run the backfill process."""
        logger.info("=" * 60)
        logger.info("MyTapo Event Backfiller")
        logger.info("=" * 60)
        logger.info(f"Source bucket: {self.source_bucket}")
        logger.info(f"Events bucket: {self.events_bucket}")
        logger.info(f"Days to process: {self.days_back}")
        logger.info(f"Devices to analyze: {list(self.profiles.keys())}")

        # Check for existing events
        existing = self._check_existing_events()
        if existing > 0:
            logger.warning(f"Found {existing} existing events in bucket")
            logger.warning("Continuing will add new events (duplicates possible)")

        # Process each device
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.days_back)

        for device_name, profile in self.profiles.items():
            logger.info(f"\nProcessing {device_name} ({profile['event_name']})...")

            detector = BackfillEventDetector(device_name, profile, self.settings)

            # Process in weekly chunks to manage memory
            chunk_start = start_date
            chunk_days = 7
            readings_processed = 0

            while chunk_start < end_date:
                chunk_end = min(chunk_start + timedelta(days=chunk_days), end_date)

                # Query power data for this chunk
                readings = self._query_power_data(device_name, chunk_start, chunk_end)
                readings_processed += len(readings)

                # Process each reading
                for power, timestamp in readings:
                    detector.process_reading(power, timestamp)

                chunk_start = chunk_end

            # Finalize any open event
            detector.finalize()

            # Write detected events
            events = detector.detected_events
            if events:
                self._write_events(events)
                logger.info(f"  -> Detected {len(events)} {profile['event_name']} events")
                logger.info(f"     ({readings_processed:,} power readings processed)")
            else:
                logger.info(f"  -> No events detected ({readings_processed:,} readings)")

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total events created: {self.total_events}")
        logger.info("\nEvents by type:")
        for event_type, count in sorted(self.events_by_type.items()):
            logger.info(f"  {event_type}: {count}")
        logger.info("=" * 60)


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Backfill historical appliance events")
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Number of days to look back (default: 365)"
    )
    args = parser.parse_args()

    backfiller = EventBackfiller(days_back=args.days)
    backfiller.run()


if __name__ == "__main__":
    main()