from __future__ import annotations

import json
from pathlib import Path

from app.validation import compare_counts, count_events_jsonl, passed_within_threshold, read_ground_truth_csv


def test_count_comparison_helpers(tmp_path: Path) -> None:
    ground_truth = tmp_path / "ground_truth.csv"
    ground_truth.write_text(
        "clip_id,expected_entry,expected_exit\n"
        "clipA,4,2\n",
        encoding="utf-8",
    )

    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            [
                json.dumps({"clip_id": "clipA", "event_type": "ENTRY"}),
                json.dumps({"clip_id": "clipA", "event_type": "ENTRY"}),
                json.dumps({"clip_id": "clipA", "event_type": "EXIT"}),
                json.dumps({"clip_id": "clipB", "event_type": "EXIT"}),
            ]
        ),
        encoding="utf-8",
    )

    rows = read_ground_truth_csv(ground_truth)
    assert len(rows) == 1
    counts = count_events_jsonl(events, clip_id="clipA")
    metrics = compare_counts(
        expected_entry=4,
        expected_exit=2,
        observed_entry=int(counts.get("ENTRY", 0)),
        observed_exit=int(counts.get("EXIT", 0)),
    )

    assert metrics["entry_abs_error"] == 2
    assert metrics["exit_abs_error"] == 1
    assert passed_within_threshold(metrics, threshold_pct=60.0) is True
    assert passed_within_threshold(metrics, threshold_pct=10.0) is False