# PROMPT: Create tests for the /stores/{id}/anomalies endpoint to ensure it returns a structured list.
# CHANGES MADE: Used heuristic events to trigger anomaly conditions.

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
        "zone_id": "CHECKOUT",
        "dwell_ms": 1200,
        "is_staff": False,
        "confidence": 0.98,
        "metadata": {
            "queue_depth": 5,
            "sku_zone": "CHECKOUT",
            "session_seq": 1,
            "dwell_seconds": 1.2,
            "source": "tests",
        },
    }


def test_anomalies_response_structure() -> None:
    STORE.clear()
    events = [sample_event(event_id=f"a{i}", visitor_id=f"VIS_{i}", event_type="BILLING_QUEUE_JOIN") for i in range(6)]
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200

    a = client.get("/stores/STORE_BLR_002/anomalies")
    assert a.status_code == 200
    payload = a.json()
    assert "anomalies" in payload
    assert isinstance(payload["anomalies"], list)


def test_anomalies_detect_entry_exit_imbalance() -> None:
    STORE.clear()
    events = [sample_event(event_id=f"b{i}", visitor_id=f"VIS_E{i}", event_type="ENTRY") for i in range(8)]
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200

    a = client.get("/stores/STORE_BLR_002/anomalies")
    assert a.status_code == 200
    payload = a.json()
    anomaly_types = {item["anomaly_type"] for item in payload["anomalies"]}
    assert "ENTRY_EXIT_IMBALANCE" in anomaly_types
