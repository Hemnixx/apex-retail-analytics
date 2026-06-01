from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_ground_truth_csv(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(row)
        return rows


def count_events_jsonl(path: str | Path, clip_id: str | None = None) -> Counter:
    events_path = Path(path)
    counts: Counter = Counter()
    with events_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            event = json.loads(line)
            if clip_id is not None and str(event.get("clip_id") or "") != clip_id:
                continue
            event_type = str(event.get("event_type") or "").upper()
            if event_type:
                counts[event_type] += 1
    return counts


def compare_counts(expected_entry: int, expected_exit: int, observed_entry: int, observed_exit: int) -> dict[str, Any]:
    def pct_error(observed: int, expected: int) -> float | None:
        if expected == 0:
            return None if observed == 0 else 100.0
        return round(100.0 * abs(observed - expected) / expected, 2)

    entry_error = pct_error(observed_entry, expected_entry)
    exit_error = pct_error(observed_exit, expected_exit)
    total_expected = expected_entry + expected_exit
    total_observed = observed_entry + observed_exit

    return {
        "expected_entry": expected_entry,
        "expected_exit": expected_exit,
        "observed_entry": observed_entry,
        "observed_exit": observed_exit,
        "entry_abs_error": abs(observed_entry - expected_entry),
        "exit_abs_error": abs(observed_exit - expected_exit),
        "entry_pct_error": entry_error,
        "exit_pct_error": exit_error,
        "total_expected": total_expected,
        "total_observed": total_observed,
        "total_abs_error": abs(total_observed - total_expected),
    }


def passed_within_threshold(metrics: dict[str, Any], threshold_pct: float) -> bool:
    entry_pct = metrics.get("entry_pct_error")
    exit_pct = metrics.get("exit_pct_error")
    entry_ok = entry_pct is None or entry_pct <= threshold_pct
    exit_ok = exit_pct is None or exit_pct <= threshold_pct
    return bool(entry_ok and exit_ok)