# Grafana Query Guide: Combining Office Devices

## Overview
The `office` and `office2` devices are stored separately in InfluxDB but can be aggregated in Grafana to show combined power consumption.

## Configuration Summary
- **office**: 192.168.178.55 (emoji: 3971)
- **office2**: 192.168.178.121 (emoji: 3971)
- Both tagged with `grafana_group: "office"` in devices.json
- **New Feature**: device_group tag is now written to InfluxDB for easier aggregation

## Grafana Query Examples

### Option 1: Using device_group Tag (Recommended - NEW)
The cleanest approach using the new device_group tag:

```flux
from(bucket: "power_consumption")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "power_consumption")
  |> filter(fn: (r) => r["_field"] == "power")
  |> filter(fn: (r) => r["device_group"] == "office")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> group(columns: ["_time"])
  |> sum(column: "_value")
  |> yield(name: "office_combined")
```

### Option 2: Sum of Both Office Devices (Legacy)
```flux
from(bucket: "power_consumption")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "power_consumption")
  |> filter(fn: (r) => r["_field"] == "power")
  |> filter(fn: (r) => r["device"] == "office" or r["device"] == "office2")
  |> group(columns: ["_time"])
  |> sum(column: "_value")
  |> group()
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> yield(name: "office_combined")
```

### Option 2: Show Both Separately + Combined Total
```flux
// Individual devices
office = from(bucket: "power_consumption")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "power_consumption")
  |> filter(fn: (r) => r["_field"] == "power")
  |> filter(fn: (r) => r["device"] == "office")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)

office2 = from(bucket: "power_consumption")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "power_consumption")
  |> filter(fn: (r) => r["_field"] == "power")
  |> filter(fn: (r) => r["device"] == "office2")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)

union(tables: [office, office2])
```

### Option 3: Show Individual + Total in Same Panel
```flux
import "experimental"

// Get both devices
data = from(bucket: "power_consumption")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "power_consumption")
  |> filter(fn: (r) => r["_field"] == "power")
  |> filter(fn: (r) => r["device"] == "office" or r["device"] == "office2")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)

// Calculate total
total = data
  |> group(columns: ["_time"])
  |> sum(column: "_value")
  |> map(fn: (r) => ({ r with device: "office_total" }))

// Combine individual + total
union(tables: [data, total])
```

## Panel Configuration Tips

### For Single "Office" Display (Combined)
1. Use **Option 1** query
2. Set panel title to "Office (Combined)"
3. Display as single stat or time series

### For Detailed View (Individual + Total)
1. Use **Option 3** query
2. Configure legend to show:
   - `office` → "Office 1"
   - `office2` → "Office 2"
   - `office_total` → "Office Total"
3. Use different colors/styles for clarity

### For Table View
```flux
from(bucket: "power_consumption")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "power_consumption")
  |> filter(fn: (r) => r["_field"] == "power")
  |> filter(fn: (r) => r["device"] == "office" or r["device"] == "office2")
  |> last()
  |> group()
  |> sort(columns: ["device"])
```

## Dashboard Variables (Optional)

Create a variable to toggle between individual/combined view:

**Variable Name:** `office_view`
**Type:** Custom
**Values:** `individual,combined,both`

Then use conditional queries based on the variable.

## Energy Consumption Calculations

For daily/monthly totals:
```flux
from(bucket: "power_consumption")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "power_consumption")
  |> filter(fn: (r) => r["_field"] == "power")
  |> filter(fn: (r) => r["device"] == "office" or r["device"] == "office2")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> sum(column: "_value")
  |> map(fn: (r) => ({ r with _value: r._value / 1000.0 }))  // Convert to kWh
```

## Cost Calculation (0.28 EUR/kWh)
```flux
from(bucket: "power_consumption")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "power_consumption")
  |> filter(fn: (r) => r["_field"] == "power")
  |> filter(fn: (r) => r["device"] == "office" or r["device"] == "office2")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> sum(column: "_value")
  |> map(fn: (r) => ({
      r with
      _value: r._value / 1000.0 * 0.28,
      _field: "cost_eur"
    }))
```

## Notes
- Both devices are tracked separately in InfluxDB (good for debugging/monitoring)
- Grafana queries aggregate them on-the-fly (flexible display)
- **NEW**: The `grafana_group` field in devices.json is now written as `device_group` tag in InfluxDB
- This makes queries cleaner and more efficient - just filter by `device_group` tag
- Backward compatible: old data without device_group tag still accessible via device names
- Adjust `v.windowPeriod` based on your time range for optimal performance

## Implementation Details

### What Changed
1. `influx_batch_writer.py`: Added optional `device_group` parameter to `add_power_measurement()`
2. `tapo_influx_consumption_dynamic.py`: Modified to read `grafana_group` from config and pass as `device_group`
3. `config/devices.json`: Both office devices now have `"grafana_group": "office"`

### Data Structure in InfluxDB
```
measurement: power_consumption
tags:
  - device: "office"           (individual device identifier)
  - device_group: "office"     (aggregation group - NEW)
fields:
  - power: 187.0               (power consumption in watts)
```

### Benefits
✅ Cleaner Grafana queries (single tag filter instead of OR conditions)
✅ Better performance (indexed tag lookup)
✅ Easier to extend (add office3, office4 without changing queries)
✅ Backward compatible (old queries still work)