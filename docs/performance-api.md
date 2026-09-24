# System performance endpoint

`GET /api/system/performance` provides a small, read-only snapshot for an
optional local performance panel. It reuses the process/system memory collector
already used by the sidebar and does not inspect audio devices, model engines,
GPU state, or filesystem paths. Polling this endpoint does not start background
work or wait for a CPU sampling interval.

Example response:

```json
{
  "total_bytes": 16911433728,
  "available_bytes": 7516192768,
  "used_bytes": 9395235960,
  "percent": 55.5,
  "process_bytes": 681574400,
  "logical_cpu_count": 16,
  "cpu_usage_percent": null,
  "cpu_usage_available": false
}
```

Memory values are byte counts, except `percent`, which is system RAM usage in
percent. If the optional platform memory collector is unavailable, memory
values are `null`. CPU utilization is currently reported as unavailable because
measuring it accurately requires sampling over time; `logical_cpu_count` is
provided as static hardware context instead. No recording state, meeting data,
secrets, or local paths are returned.
