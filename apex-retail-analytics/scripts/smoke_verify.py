from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
STORE_ID = sys.argv[2] if len(sys.argv) > 2 else "STORE_BLR_002"


def fetch(path: str) -> dict:
    url = f"{BASE_URL.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    try:
        health = fetch("/health")
        metrics = fetch(f"/stores/{STORE_ID}/metrics")
        summary = fetch("/analytics/summary")
    except urllib.error.URLError as exc:
        print(f"SMOKE_FAIL: unable to reach API: {exc}")
        return 1

    required_health = {"status", "total_events_stored", "timestamp", "warnings"}
    required_metrics = {"total_events", "unique_visitors", "average_dwell_ms", "estimated_conversion_rate"}
    required_summary = {"total_events", "unique_visitors", "average_dwell_ms", "estimated_conversion_rate"}

    missing_health = required_health - set(health)
    missing_metrics = required_metrics - set(metrics)
    missing_summary = required_summary - set(summary)

    if missing_health or missing_metrics or missing_summary:
        print("SMOKE_FAIL: missing fields detected")
        print(f"health_missing={sorted(missing_health)}")
        print(f"metrics_missing={sorted(missing_metrics)}")
        print(f"summary_missing={sorted(missing_summary)}")
        return 1

    print("SMOKE_OK")
    print(json.dumps({
        "health_status": health.get("status"),
        "total_events_stored": health.get("total_events_stored"),
        "store_total_events": metrics.get("total_events"),
        "store_unique_visitors": metrics.get("unique_visitors"),
        "summary_conversion_rate": summary.get("estimated_conversion_rate"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())