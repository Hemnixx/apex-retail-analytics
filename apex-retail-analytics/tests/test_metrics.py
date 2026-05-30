# PROMPT: Generate tests for the /stores/{id}/metrics and /stores/{id}/funnel endpoints. Keep edge cases in mind.
# CHANGES MADE: Adjusted expected fields to match in-memory EventStore summary/funnel shapes.

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.store import STORE

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
    STORE.events.clear()
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
