from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from urllib import error as urlerror
from urllib import request as urlrequest


DEFAULT_API_URL = "http://127.0.0.1:8000"


def fetch_json(url: str) -> dict:
    request = urlrequest.Request(url, headers={"Accept": "application/json"})
    with urlrequest.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def format_timestamp(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return value


def render_dashboard(api_url: str, store_id: str) -> None:
    health = fetch_json(f"{api_url.rstrip('/')}/health")
    metrics = fetch_json(f"{api_url.rstrip('/')}/stores/{store_id}/metrics")
    funnel = fetch_json(f"{api_url.rstrip('/')}/stores/{store_id}/funnel")
    anomalies = fetch_json(f"{api_url.rstrip('/')}/stores/{store_id}/anomalies")

    clear_screen()
    print(f"Apex Retail Live Dashboard  |  store={store_id}  |  api={api_url}")
    print("=" * 76)
    print(f"Health: {health.get('status', '-')}")
    print(f"Last store timestamp: {format_timestamp((health.get('last_event_timestamp_by_store') or {}).get(store_id))}")
    print(f"Warnings: {', '.join(health.get('warnings', [])) or '-'}")
    print()
    print(f"Total events: {metrics.get('total_events', 0)}")
    print(f"Unique visitors: {metrics.get('unique_visitors', 0)}")
    print(f"Conversion rate: {metrics.get('estimated_conversion_rate', 0):.2%}")
    print(f"Avg dwell ms: {metrics.get('average_dwell_ms', 0):.2f}")
    print()
    print("Funnel:")
    for stage in funnel.get("stages", []):
        print(f"  - {stage.get('name'):<14} count={stage.get('count', 0):<4} dropoff={stage.get('dropoff_pct', 0):>5}%")
    print()
    print("Anomalies:")
    for anomaly in anomalies.get("anomalies", []):
        print(f"  - {anomaly.get('severity', '-')}: {anomaly.get('anomaly_type', '-')} | {anomaly.get('message', '-')}")
    if not anomalies.get("anomalies"):
        print("  - none")
    print("=" * 76)
    print("Press Ctrl+C to stop.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live store dashboard")
    parser.add_argument("--api-url", type=str, default=DEFAULT_API_URL)
    parser.add_argument("--store-id", type=str, default="STORE_BLR_002")
    parser.add_argument("--interval", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        while True:
            try:
                render_dashboard(args.api_url, args.store_id)
            except urlerror.URLError as exc:
                clear_screen()
                print(f"Unable to reach API at {args.api_url}: {exc}")
                print("Waiting for the API... press Ctrl+C to stop.")
            time.sleep(max(0.5, args.interval))
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
