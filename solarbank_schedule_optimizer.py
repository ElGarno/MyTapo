"""
Solarbank Schedule Optimizer for Anker Solarbank 2 E1600 Plus.

Queries historical power consumption data from InfluxDB, calculates an
average hourly consumption profile across all days, and generates an
optimized custom schedule for the Solarbank's user-defined mode.

Important: The induction cooktop is not tracked (high-voltage connection),
but contributes significant load during cooking times (~12:30 and 18:00-19:30).
These time windows are boosted in the final profile.
"""

import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuration ---

# Solarbank output limits (Anker Solarbank 2 E1600 Plus)
SOLARBANK_MIN_OUTPUT_W = 0
SOLARBANK_MAX_OUTPUT_W = 800

# Schedule granularity: 30-minute slots (0.5h)
SLOT_MINUTES = 30
SLOTS_PER_DAY = 48

# Devices to exclude from consumption profile (solar = generation, not consumption)
EXCLUDE_DEVICES = {"solar"}

# Cooking time boost: estimated additional load from untracked induction cooktop
# start/end as fractional hours (e.g., 12.5 = 12:30)
COOKING_BOOSTS = [
    {"start": 12.0, "end": 13.5, "boost_w": 800, "label": "Lunch cooking"},
    {"start": 17.5, "end": 19.5, "boost_w": 1200, "label": "Dinner cooking"},
]

# How many days of history to analyze (more days = more stable average)
ANALYSIS_DAYS = 90

# Cost per kWh for savings calculation
COST_PER_KWH = 0.28


def slot_label(slot_index):
    """Convert slot index (0-47) to time label like '08:30'."""
    h = slot_index // 2
    m = (slot_index % 2) * 30
    return f"{h:02d}:{m:02d}"


def slot_range_label(slot_index):
    """Convert slot index to range label like '08:30 - 09:00'."""
    return f"{slot_label(slot_index)} - {slot_label((slot_index + 1) % SLOTS_PER_DAY)}"


def get_influx_client():
    """Create InfluxDB client from environment variables."""
    host = os.getenv("INFLUXDB_HOST", "192.168.178.114")
    port = os.getenv("INFLUXDB_PORT", "8088")
    token = os.getenv("INFLUXDB_TOKEN")
    return InfluxDBClient(
        url=f"http://{host}:{port}",
        token=token,
        org="None"
    )


def query_half_hourly_profile(days=ANALYSIS_DAYS):
    """
    Query InfluxDB for average power consumption per 30-min slot,
    summed across all tracked devices (excluding solar).

    Returns:
        dict: {slot_index (0-47): average_watts}
              slot 0 = 00:00-00:30, slot 1 = 00:30-01:00, etc.
    """
    bucket = os.getenv("INFLUXDB_BUCKET", "power_consumption")
    start_time = f"-{days}d"

    exclude_filter = " and ".join(
        f'r["device"] != "{dev}"' for dev in EXCLUDE_DEVICES
    )

    # Flux query: aggregate to 30min per device, then sum across devices per window,
    # then average across days by slot-of-day
    query = f'''
    import "date"

    from(bucket: "{bucket}")
        |> range(start: {start_time})
        |> filter(fn: (r) => r["_measurement"] == "power_consumption")
        |> filter(fn: (r) => r["_field"] == "power")
        |> filter(fn: (r) => {exclude_filter})
        |> aggregateWindow(every: 30m, fn: mean, createEmpty: false)
        |> group(columns: ["_time"])
        |> sum(column: "_value")
        |> map(fn: (r) => ({{ r with slot: date.hour(t: r._time) * 2 + (if date.minute(t: r._time) >= 30 then 1 else 0) }}))
        |> group(columns: ["slot"])
        |> mean(column: "_value")
    '''

    logger.info(f"Querying InfluxDB for {days} days of 30-min consumption data...")

    profile = {}

    with get_influx_client() as client:
        query_api = client.query_api()
        tables = query_api.query(query)

        for table in tables:
            for record in table.records:
                slot = record.values.get("slot")
                value = record.get_value()
                if slot is not None and value is not None:
                    profile[int(slot)] = round(float(value), 1)

    # Fill missing slots with 0
    for s in range(SLOTS_PER_DAY):
        if s not in profile:
            profile[s] = 0.0

    logger.info(f"Retrieved profile for {len(profile)} half-hour slots")
    return dict(sorted(profile.items()))


def query_half_hourly_profile_fallback(days=ANALYSIS_DAYS):
    """
    Fallback query: fetch 30-min aggregated data per device and compute
    slot averages in Python.

    Returns:
        dict: {slot_index (0-47): average_watts (sum across devices)}
    """
    bucket = os.getenv("INFLUXDB_BUCKET", "power_consumption")
    start_time = f"-{days}d"

    exclude_filter = " and ".join(
        f'r["device"] != "{dev}"' for dev in EXCLUDE_DEVICES
    )

    query = f'''
    from(bucket: "{bucket}")
        |> range(start: {start_time})
        |> filter(fn: (r) => r["_measurement"] == "power_consumption")
        |> filter(fn: (r) => r["_field"] == "power")
        |> filter(fn: (r) => {exclude_filter})
        |> aggregateWindow(every: 30m, fn: mean, createEmpty: false)
    '''

    logger.info(f"Fallback query: fetching 30-min means per device for {days} days...")

    from collections import defaultdict, Counter

    # Collect: {(date, slot): {device: mean_power}}
    slot_device_data = defaultdict(lambda: defaultdict(float))

    with get_influx_client() as client:
        query_api = client.query_api()
        tables = query_api.query(query)

        record_count = 0
        for table in tables:
            for record in table.records:
                time = record.get_time()
                value = record.get_value()
                device = record.values.get("device", "unknown")
                if time and value is not None:
                    date_key = time.strftime("%Y-%m-%d")
                    slot = time.hour * 2 + (1 if time.minute >= 30 else 0)
                    slot_device_data[(date_key, slot)][device] = float(value)
                    record_count += 1

    logger.info(f"Fetched {record_count} half-hourly records")

    if not slot_device_data:
        logger.warning("No data returned from InfluxDB")
        return {s: 0.0 for s in range(SLOTS_PER_DAY)}

    # Sum across devices per (date, slot), then average across days per slot
    slot_totals = defaultdict(float)
    slot_counts = Counter()

    for (date_key, slot), devices in slot_device_data.items():
        total_power = sum(devices.values())
        slot_totals[slot] += total_power
        slot_counts[slot] += 1

    profile = {}
    for s in range(SLOTS_PER_DAY):
        if slot_counts[s] > 0:
            profile[s] = round(slot_totals[s] / slot_counts[s], 1)
        else:
            profile[s] = 0.0

    num_days = len(set(dk for dk, _ in slot_device_data.keys()))
    logger.info(f"Computed half-hourly profile from {num_days} days of data")

    return dict(sorted(profile.items()))


def apply_cooking_boost(profile):
    """
    Apply cooking time boosts to the half-hourly profile.
    The induction cooktop is not tracked but adds significant load.

    Returns:
        dict: {slot_index: boosted_watts}
    """
    boosted = dict(profile)

    for boost in COOKING_BOOSTS:
        start = boost["start"]  # fractional hour, e.g. 12.5 = 12:30
        end = boost["end"]
        boost_w = boost["boost_w"]

        for slot in range(SLOTS_PER_DAY):
            slot_start = slot * 0.5  # fractional hour
            slot_end = slot_start + 0.5

            # Calculate overlap between cooking window and this slot
            overlap_start = max(slot_start, start)
            overlap_end = min(slot_end, end)
            overlap = max(0, overlap_end - overlap_start)
            fraction = overlap / 0.5  # fraction of the 30-min slot

            if fraction > 0:
                boosted[slot] = round(boosted.get(slot, 0) + boost_w * fraction, 1)

    return boosted


def compute_solarbank_schedule(boosted_profile):
    """
    Convert the boosted half-hourly profile into a Solarbank custom schedule.
    Clamps values to [SOLARBANK_MIN_OUTPUT_W, SOLARBANK_MAX_OUTPUT_W].
    Rounds to nearest 50W for practical app input.

    Returns:
        dict: {slot_index: output_watts}
    """
    schedule = {}
    for slot, watts in boosted_profile.items():
        clamped = max(SOLARBANK_MIN_OUTPUT_W, min(SOLARBANK_MAX_OUTPUT_W, watts))
        # Round to nearest 50W for easier input in the app
        rounded = round(clamped / 50) * 50
        schedule[slot] = rounded
    return schedule


def print_schedule_table(measured_profile, boosted_profile, schedule):
    """Print a formatted comparison table with 30-min slots."""
    print("\n" + "=" * 80)
    print("  SOLARBANK 2 E1600 PLUS - OPTIMIZED CUSTOM SCHEDULE (30-min slots)")
    print("=" * 80)
    print(f"  {'Slot':<15} {'Measured (W)':<15} {'+ Cooking (W)':<15} {'Schedule (W)':<15} {'Bar'}")
    print("-" * 80)

    for slot in range(SLOTS_PER_DAY):
        measured = measured_profile.get(slot, 0)
        boosted = boosted_profile.get(slot, 0)
        sched = schedule.get(slot, 0)
        bar_len = int(sched / SOLARBANK_MAX_OUTPUT_W * 25)
        bar = "#" * bar_len

        slot_start = slot * 0.5
        cooking_marker = ""
        for boost in COOKING_BOOSTS:
            if boost["start"] <= slot_start < boost["end"]:
                cooking_marker = " *"
                break

        print(f"  {slot_label(slot):<13} {measured:>10.0f}     {boosted:>10.0f}     {sched:>10d}     {bar}{cooking_marker}")

    print("-" * 80)
    print("  * = cooking boost applied (untracked induction cooktop)")

    # Each slot is 0.5h, so Wh per slot = W * 0.5
    total_daily_wh = sum(w * 0.5 for w in schedule.values())
    total_daily_kwh = total_daily_wh / 1000
    print(f"\n  Total daily Solarbank output: {total_daily_wh:,.0f} Wh ({total_daily_kwh:.1f} kWh)")
    print(f"  Estimated daily savings:      {total_daily_kwh * COST_PER_KWH:.2f} EUR")
    print(f"  Estimated monthly savings:    {total_daily_kwh * COST_PER_KWH * 30:.2f} EUR")
    print("=" * 80)


def create_profile_chart(measured_profile, boosted_profile, schedule, output_path="solarbank_schedule.png"):
    """Create a visualization of the consumption profile and schedule (30-min slots)."""
    slots = list(range(SLOTS_PER_DAY))
    x_hours = [s * 0.5 for s in slots]  # x-axis in fractional hours
    measured = [measured_profile.get(s, 0) for s in slots]
    boosted = [boosted_profile.get(s, 0) for s in slots]
    sched = [schedule.get(s, 0) for s in slots]

    fig, ax = plt.subplots(figsize=(16, 7))

    # Measured consumption (light blue area)
    ax.fill_between(x_hours, measured, alpha=0.3, color='#2196F3', step='mid', label='Measured consumption')
    ax.step(x_hours, measured, color='#2196F3', linewidth=1.5, where='mid')

    # Boosted profile (dashed line showing cooking estimate)
    ax.step(x_hours, boosted, color='#FF9800', linewidth=1.5, linestyle='--', where='mid', label='Incl. cooking estimate')

    # Solarbank schedule (green bars)
    ax.bar(x_hours, sched, alpha=0.5, color='#4CAF50', width=0.45, label='Solarbank schedule', zorder=2)

    # Solarbank max line
    ax.axhline(y=SOLARBANK_MAX_OUTPUT_W, color='red', linestyle=':', alpha=0.5, label=f'Solarbank max ({SOLARBANK_MAX_OUTPUT_W}W)')

    # Cooking time shading
    for boost in COOKING_BOOSTS:
        ax.axvspan(boost["start"], boost["end"], alpha=0.1, color='red', zorder=0)
        mid = (boost["start"] + boost["end"]) / 2
        ax.text(mid, ax.get_ylim()[1] * 0.95 if ax.get_ylim()[1] > 0 else 500,
                boost["label"], ha='center', va='top', fontsize=8, color='red', alpha=0.7)

    ax.set_xlabel('Time of Day', fontsize=12)
    ax.set_ylabel('Power (W)', fontsize=12)
    ax.set_title('Solarbank 2 E1600 Plus - Optimized Custom Schedule (30-min slots)\n'
                 '(averaged over historical consumption data)', fontsize=13)
    ax.set_xticks(range(25))
    ax.set_xticklabels([f'{h:02d}:00' for h in range(25)], rotation=45, ha='right', fontsize=8)
    ax.set_xlim(-0.25, 24.25)
    ax.yaxis.set_major_locator(ticker.MultipleLocator(100))
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    logger.info(f"Chart saved to {output_path}")
    plt.close()


def print_app_input_format(schedule):
    """
    Print the schedule in a compact format for the Anker app.
    Merges consecutive slots with the same wattage into ranges.
    """
    print("\n" + "=" * 55)
    print("  ANKER APP INPUT (Custom Schedule - 30-min slots)")
    print("=" * 55)
    print("  Enter these time ranges in the Anker app:\n")

    # Merge consecutive slots with same wattage
    ranges = []
    current_start = 0
    current_watts = schedule.get(0, 0)

    for slot in range(1, SLOTS_PER_DAY):
        watts = schedule.get(slot, 0)
        if watts != current_watts:
            ranges.append((current_start, slot, current_watts))
            current_start = slot
            current_watts = watts
    ranges.append((current_start, SLOTS_PER_DAY, current_watts))

    for start_slot, end_slot, watts in ranges:
        end_label = slot_label(end_slot % SLOTS_PER_DAY) if end_slot < SLOTS_PER_DAY else "00:00"
        print(f"  {slot_label(start_slot)} - {end_label}  →  {watts:>4d} W")

    print(f"\n  ({len(ranges)} time ranges)")
    print("=" * 55)


def main():
    logger.info("Starting Solarbank Schedule Optimizer (30-min granularity)...")

    # Try primary query first, fall back to Python-based aggregation
    try:
        measured_profile = query_half_hourly_profile()
        if all(v == 0 for v in measured_profile.values()):
            logger.warning("Primary query returned all zeros, trying fallback...")
            measured_profile = query_half_hourly_profile_fallback()
    except Exception as e:
        logger.warning(f"Primary query failed ({e}), trying fallback...")
        measured_profile = query_half_hourly_profile_fallback()

    if all(v == 0 for v in measured_profile.values()):
        logger.error("No consumption data available. Check InfluxDB connection and data.")
        return

    # Print raw measured profile
    print("\n--- Measured 30-min average (all devices, excl. solar) ---")
    for slot in range(SLOTS_PER_DAY):
        print(f"  {slot_label(slot)}  {measured_profile[slot]:>7.1f} W")

    # Apply cooking boost
    boosted_profile = apply_cooking_boost(measured_profile)

    # Compute Solarbank schedule
    schedule = compute_solarbank_schedule(boosted_profile)

    # Output results
    print_schedule_table(measured_profile, boosted_profile, schedule)
    print_app_input_format(schedule)

    # Generate chart
    output_path = os.path.join(os.path.dirname(__file__), "solarbank_schedule.png")
    create_profile_chart(measured_profile, boosted_profile, schedule, output_path)

    logger.info("Done. Check solarbank_schedule.png for the visual profile.")


if __name__ == "__main__":
    main()