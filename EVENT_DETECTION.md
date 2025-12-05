# Appliance Event Detection System

This document describes the event detection service that automatically identifies appliance usage patterns from power consumption data and provides analytics for dashboards.

## Overview

The Event Detection System monitors power readings from Tapo smart plugs and detects discrete usage events (e.g., making espresso, running the dryer, charging an e-bike). Events are stored in a dedicated InfluxDB bucket for analytics and visualization.

**Key Features:**
- Automatic detection of appliance usage based on power thresholds
- Configurable profiles for different appliance types
- Event storage in InfluxDB for time-series analysis
- AWTRIX display notifications (optional)
- Pushover daily summaries
- Grafana dashboard generation

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐
│  power_consumption  │────▶│   Event Detector     │
│    (InfluxDB)       │     │   (event_detector.py)│
└─────────────────────┘     └──────────┬───────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
           ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
           │appliance_events│  │    AWTRIX     │  │   Pushover    │
           │  (InfluxDB)    │  │   Display     │  │ Notifications │
           └───────┬───────┘  └───────────────┘  └───────────────┘
                   │
                   ▼
           ┌───────────────┐
           │   Analytics   │───▶ CSV exports, Grafana dashboards
           │   Generator   │
           └───────────────┘
```

## Configuration

### Appliance Profiles

Profiles are defined in `config/appliance_profiles.json`:

```json
{
  "profiles": {
    "kaffe_bar": {
      "event_name": "espresso",
      "event_name_plural": "espressos",
      "detection_type": "spike",
      "threshold_on": 800,
      "threshold_off": 50,
      "min_duration_seconds": 20,
      "max_duration_seconds": 180,
      "cooldown_seconds": 60,
      "track_duration": true,
      "track_energy": true,
      "awtrix_icon": "4049"
    }
  }
}
```

### Profile Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `event_name` | Name of the detected event | `"espresso"` |
| `event_name_plural` | Plural form for summaries | `"espressos"` |
| `detection_type` | Detection algorithm (`spike`, `sustained`, `cycle`) | `"spike"` |
| `threshold_on` | Power (W) to start event detection | `800` |
| `threshold_off` | Power (W) to end event detection | `50` |
| `min_duration_seconds` | Minimum duration for valid event | `20` |
| `max_duration_seconds` | Maximum duration (null = unlimited) | `180` |
| `cooldown_seconds` | Wait time before detecting next event | `60` |
| `track_duration` | Include duration in analytics | `true` |
| `track_energy` | Calculate energy consumption | `true` |
| `awtrix_icon` | LaMetric icon ID for AWTRIX display | `"4049"` |

### Currently Configured Appliances

| Device | Event | On Threshold | Off Threshold | Duration |
|--------|-------|--------------|---------------|----------|
| `kaffe_bar` | espresso | >800W | <50W | 20s - 3min |
| `television` | tv_session | >30W | <10W | 1min+ |
| `hwr_charger` | ebike_charge | >100W | <20W | 5min+ |
| `bathroom` | hairdryer | >1000W | <50W | 30s - 15min |
| `kitchen` | airfryer | >1000W | <100W | 3min - 1h |
| `washing_machine` | wash_cycle | >100W | <10W | 10min - 3h |
| `washing_dryer` | dry_cycle | >40W | <10W | 10min - 3h |

### Global Settings

```json
{
  "settings": {
    "polling_interval_seconds": 15,
    "cooling_confirmation_seconds": 30,
    "hourly_summary_enabled": true,
    "daily_summary_hour": 21,
    "daily_summary_minute": 0,
    "analytics_generation_hour": 2,
    "enable_awtrix_on_event": false,
    "enable_pushover_daily": true
  }
}
```

## AWTRIX Display Integration

The event detector sends notifications to an AWTRIX LED matrix display.

### Notification Types

#### 1. Event Completion (optional)
When `enable_awtrix_on_event: true`:
- **Text:** `"{event_name}: {duration}"` (e.g., "espresso: 45s")
- **Icon:** Appliance-specific from profile
- **Color:** Green (`#00FF00`)
- **Duration:** 10 seconds
- **Sound:** Chime

#### 2. Hourly Summary
When `hourly_summary_enabled: true`:
- **Text:** Event counts and durations from last hour
- **Icon:** Clock (`2103`)
- **Color:** Light blue (`#87CEEB`)
- **Duration:** 15 seconds

#### 3. Daily Summary
At configured time (default 21:00):
- **Text:** `"Today: {events summary}"`
- **Icon:** Calendar (`1543`)
- **Color:** Gold (`#FFD700`)
- **Duration:** 20 seconds
- **Sound:** Chime

### AWTRIX Icons Used

| Appliance | Icon ID | Description |
|-----------|---------|-------------|
| Espresso | 4049 | Coffee cup |
| TV | 1407 | Television |
| E-bike | 51299 | Bicycle |
| Hairdryer | 12210 | Hair dryer |
| Airfryer | 2965 | Cooking |
| Washing | 26673 | Washing machine |
| Dryer | 56907 | Dryer |

## InfluxDB Data Structure

### Events Bucket: `appliance_events`

```
measurement: event
tags:
  - device: "kaffe_bar"
  - event_type: "espresso"
  - hour_of_day: "8"
  - day_of_week: "1"
fields:
  - duration_seconds: 45.0
  - energy_wh: 12.5
  - peak_power: 1200.0
  - avg_power: 950.0
timestamp: 2024-01-15T08:30:00Z
```

### Flux Query Examples

#### Count Events Today
```flux
from(bucket: "appliance_events")
  |> range(start: today())
  |> filter(fn: (r) => r["_measurement"] == "event")
  |> filter(fn: (r) => r["event_type"] == "espresso")
  |> count()
```

#### Daily Event Counts (Last 30 Days)
```flux
from(bucket: "appliance_events")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "event")
  |> group(columns: ["event_type"])
  |> aggregateWindow(every: 1d, fn: count, createEmpty: false)
```

#### Average Duration by Event Type
```flux
from(bucket: "appliance_events")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "event")
  |> filter(fn: (r) => r["_field"] == "duration_seconds")
  |> group(columns: ["event_type"])
  |> mean()
```

#### Total Energy Consumption
```flux
from(bucket: "appliance_events")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "event")
  |> filter(fn: (r) => r["_field"] == "energy_wh")
  |> group(columns: ["event_type"])
  |> sum()
  |> map(fn: (r) => ({ r with _value: r._value / 1000.0 }))  // Convert to kWh
```

## Grafana Dashboard

The analytics generator creates visualizations for:

### Available Panels

| Panel Type | Description | Data |
|------------|-------------|------|
| **Stat** | Event count today per type | Real-time from InfluxDB |
| **Heatmap** | Event frequency by hour × day of week | CSV export |
| **Time Series** | Daily event counts over time | InfluxDB query |
| **Bar Chart** | Average duration by event type | JSON stats |
| **Table** | Energy consumption and costs | JSON stats |

### Generated Files

The analytics generator outputs to `analytics/` directory:

| File | Description |
|------|-------------|
| `heatmap_all.csv` | All events by hour/day |
| `heatmap_{event_type}.csv` | Per-event-type heatmaps |
| `daily_counts.csv` | Daily event counts |
| `duration_stats.json` | Duration statistics |
| `energy_stats.json` | Energy consumption stats |
| `weekly_summary.json` | Last 7 days summary |
| `grafana_dashboard.json` | Dashboard template |

### Sample Heatmap CSV

```csv
hour,day_of_week,day_name,count
8,0,Mon,5
8,1,Tue,3
9,0,Mon,2
...
```

## Running the Service

### Local Development

```bash
# Run event detector
uv run python event_detector.py

# Generate analytics manually
uv run python analytics_generator.py
```

### Docker Deployment

```bash
# Build and run
docker-compose up event_detector

# View logs
docker-compose logs -f event_detector
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `INFLUXDB_HOST` | InfluxDB server address | `192.168.178.114` |
| `INFLUXDB_PORT` | InfluxDB port | `8088` |
| `INFLUXDB_BUCKET` | Source bucket for power data | `power_consumption` |
| `INFLUXDB_EVENTS_BUCKET` | Bucket for detected events | `appliance_events` |
| `INFLUXDB_TOKEN` | InfluxDB authentication token | - |
| `AWTRIX_HOST` | AWTRIX display IP address | `192.168.178.108` |
| `AWTRIX_PORT` | AWTRIX port | `80` |
| `PUSHOVER_USER_GROUP_WOERIS` | Pushover user/group key | - |

## Adding New Appliances

1. **Identify the device name** in your `config/devices.json`

2. **Determine thresholds** by observing power patterns:
   - What power level indicates the appliance is "on"?
   - What power level indicates it's "off"?
   - How long does a typical cycle last?

3. **Add profile** to `config/appliance_profiles.json`:
   ```json
   "device_name": {
     "event_name": "my_event",
     "event_name_plural": "my events",
     "detection_type": "sustained",
     "threshold_on": 100,
     "threshold_off": 20,
     "min_duration_seconds": 60,
     "max_duration_seconds": null,
     "cooldown_seconds": 120,
     "track_duration": true,
     "track_energy": true,
     "awtrix_icon": "1234"
   }
   ```

4. **Restart the service** - the detector will automatically pick up the new profile

## Detection Types

| Type | Use Case | Behavior |
|------|----------|----------|
| `spike` | Short bursts (espresso, hairdryer) | Detects quick on/off cycles |
| `sustained` | Long usage (TV, charging) | Tracks extended power draw |
| `cycle` | Appliances with varying power (washer) | Handles fluctuating loads |

## Troubleshooting

### Events Not Detected

1. **Check power thresholds** - monitor raw power data to verify thresholds
2. **Verify device name** - must match exactly in `devices.json`
3. **Check duration limits** - event may be too short or too long
4. **Review cooldown** - previous event may still be in cooldown

### Missing AWTRIX Notifications

1. **Verify `enable_awtrix_on_event`** is `true` in settings
2. **Check AWTRIX connectivity** - test with `awtrix_client.test_connection()`
3. **Review logs** for connection errors

### InfluxDB Write Failures

1. **Verify bucket exists** - create `appliance_events` bucket in InfluxDB
2. **Check token permissions** - must have write access to events bucket
3. **Review network connectivity** to InfluxDB server