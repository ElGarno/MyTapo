# Grafana Query Guide: Combining Office Devices

## Overview
The `office` and `office2` devices are stored separately in InfluxDB but can be aggregated in Grafana to show combined power consumption.

## Configuration Summary
- **office**: 192.168.178.55 (emoji: 3971)
- **office2**: 192.168.178.121 (emoji: 3971)
- Both tagged with `grafana_group: "office"` in devices.json

## Grafana Query Examples

### Option 1: Sum of Both Office Devices (Recommended)
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
- The `grafana_group` field in devices.json is for documentation (not used by InfluxDB)
- Adjust `v.windowPeriod` based on your time range for optimal performance