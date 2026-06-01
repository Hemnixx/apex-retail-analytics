from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.validation import compare_counts, count_events_jsonl, passed_within_threshold, read_ground_truth_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare ground-truth entry/exit counts against detected events.")
    parser.add_argument("ground_truth_csv", help="CSV with clip_id, expected_entry, expected_exit")
    parser.add_argument("events_jsonl", help="JSONL file containing detector events")
    parser.add_argument("--clip-id", default=None, help="Optional clip_id filter for JSONL events")
    parser.add_argument("--threshold", type=float, default=20.0, help="Maximum allowed percent error per count")
    args = parser.parse_args()

    rows = read_ground_truth_csv(args.ground_truth_csv)
    if not rows:
        print("ground_truth_csv is empty", file=sys.stderr)
        return 2

    selected_row = None
    if args.clip_id is None:
        selected_row = rows[0]
    else:
        for row in rows:
            if str(row.get("clip_id") or "") == args.clip_id:
                selected_row = row
                break
        if selected_row is None:
            print(f"clip_id '{args.clip_id}' not found in ground_truth_csv", file=sys.stderr)
            return 2

    expected_entry = int(selected_row.get("expected_entry") or 0)
    expected_exit = int(selected_row.get("expected_exit") or 0)
    counts = count_events_jsonl(args.events_jsonl, clip_id=args.clip_id)
    metrics = compare_counts(
        expected_entry=expected_entry,
        expected_exit=expected_exit,
        observed_entry=int(counts.get("ENTRY", 0)),
        observed_exit=int(counts.get("EXIT", 0)),
    )
    metrics["clip_id"] = selected_row.get("clip_id")
    metrics["passed"] = passed_within_threshold(metrics, args.threshold)

    print(json.dumps(metrics, indent=2))
    return 0 if metrics["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())