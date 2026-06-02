# PROMPT: Generate tests for the /stores/{id}/metrics and /stores/{id}/funnel endpoints. Keep edge cases in mind.
# CHANGES MADE: Adjusted expected fields to match in-memory EventStore summary/funnel shapes.

from __future__ import annotations

from pathlib import Path
import json

from fastapi.testclient import TestClient

from app.main import app
from app.event_store import EventStore
from app.store import STORE
from app.schemas import RetailEvent

client = TestClient(app)


def sample_event(event_id: str = "evt-1", visitor_id: str = "VIS_001", event_type: str = "ENTRY", store_id: str = "STORE_BLR_002") -> dict:
    return {
        "event_id": event_id,
        "store_id": store_id,
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": "2026-05-30T00:00:00Z",
        "zone_id": "ENTRANCE",
        "dwell_ms": 1200,
        "is_staff": False,
        "confidence": 0.98,
        "metadata": {
            "queue_depth": 2,
            "sku_zone": "ENTRANCE",
            "session_seq": 1,
            "dwell_seconds": 1.2,
            "source": "tests",
        },
    }


def test_store_metrics_and_funnel() -> None:
    STORE.clear()
    # ingest some events spanning entry -> dwell -> exit -> purchase
    events = [
        sample_event(event_id="m1", visitor_id="VIS_A", event_type="ENTRY"),
        sample_event(event_id="m2", visitor_id="VIS_A", event_type="DWELL"),
        sample_event(event_id="m3", visitor_id="VIS_A", event_type="EXIT"),
        sample_event(event_id="m4", visitor_id="VIS_B", event_type="ENTRY"),
        sample_event(event_id="m5", visitor_id="VIS_B", event_type="BILLING_QUEUE_JOIN"),
        sample_event(event_id="m6", visitor_id="VIS_B", event_type="PURCHASE"),
    ]

    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    ingest = r.json()
    assert ingest["ingested"] == 6

    metrics = client.get("/stores/STORE_BLR_002/metrics")
    assert metrics.status_code == 200
    m = metrics.json()
    assert m["entry_events"] >= 2
    assert m["estimated_conversion_rate"] >= 0.0

    funnel = client.get("/stores/STORE_BLR_002/funnel")
    assert funnel.status_code == 200
    f = funnel.json()
    assert f["entry_count"] >= 1
    assert "stages" in f
    stage_counts = [stage["count"] for stage in f["stages"]]
    assert stage_counts == sorted(stage_counts, reverse=True)
    assert f["entry_count"] >= f["zone_visit_count"] >= f["billing_queue_count"] >= f["purchase_count"]


def test_pos_correlated_conversion(tmp_path: Path) -> None:
    pos_path = tmp_path / "transaction.csv"
    pos_path.write_text(
        "store_id,transaction_id,timestamp,basket_value_inr\n"
        "STORE_BLR_002,TXN_0001,2026-05-30T14:06:00Z,1250.00\n",
        encoding="utf-8",
    )
    store = EventStore(db_path=tmp_path / "events.sqlite3", pos_transactions_path=pos_path)
    store.clear()
    events = [
        sample_event(event_id="p1", visitor_id="VIS_POS", event_type="ENTRY"),
        sample_event(event_id="p2", visitor_id="VIS_POS", event_type="BILLING_QUEUE_JOIN"),
        sample_event(event_id="p3", visitor_id="VIS_POS", event_type="EXIT"),
    ]
    events[0]["timestamp"] = "2026-05-30T14:00:00Z"
    events[1]["timestamp"] = "2026-05-30T14:04:00Z"
    events[2]["timestamp"] = "2026-05-30T14:07:00Z"
    store.ingest([RetailEvent.model_validate(event) for event in events])

    metrics = store.metrics("STORE_BLR_002")
    assert metrics.conversion_basis == "pos_correlated"
    assert metrics.estimated_conversion_rate == 1.0

    funnel = store.funnel("STORE_BLR_002")
    assert funnel.purchase_count == 1


def test_store_status_uses_layout(tmp_path: Path) -> None:
    layout_path = tmp_path / "store_layout.json"
    layout_path.write_text(
        json.dumps(
            {
                "stores": [
                    {
                        "store_id": "STORE_BLR_002",
                        "zones": ["ENTRANCE", "MAIN_FLOOR", "CHECKOUT"],
                        "camera_coverage": {"CAM_ENTRY_01": ["ENTRANCE", "CHECKOUT"]},
                        "opening_hours": "00:00-23:59",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = EventStore(db_path=tmp_path / "events.sqlite3", store_layout_path=layout_path)
    store.clear()
    store.ingest([RetailEvent.model_validate(sample_event(event_id="s1"))])

    status = store.store_status("STORE_BLR_002")
    assert status["store_id"] == "STORE_BLR_002"
    assert status["is_open"] is True
    assert status["opening_hours"] == "00:00-23:59"
    assert status["camera_coverage"]["CAM_ENTRY_01"] == ["ENTRANCE", "CHECKOUT"]
