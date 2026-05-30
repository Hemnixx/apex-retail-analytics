from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.store import STORE


client = TestClient(app)


def sample_event(event_id: str = "evt-1", visitor_id: str = "VIS_001", event_type: str = "ENTRY") -> dict:
    return {
        "event_id": event_id,
        "store_id": "STORE_BLR_002",
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


def test_health_endpoint() -> None:
    STORE.events.clear()
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert "timestamp" in payload


def test_ingest_and_summary_flow() -> None:
    STORE.events.clear()
    events = [
        sample_event(event_id="evt-1", visitor_id="VIS_001", event_type="ENTRY"),
        sample_event(event_id="evt-2", visitor_id="VIS_001", event_type="DWELL"),
        sample_event(event_id="evt-3", visitor_id="VIS_001", event_type="EXIT"),
    ]

    ingest_response = client.post("/events/ingest", json=events)
    assert ingest_response.status_code == 200
    assert ingest_response.json()["ingested"] == 3

    duplicate_response = client.post("/events/ingest", json=[events[0]])
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["duplicates"] == 1

    summary_response = client.get("/analytics/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_events"] == 3
    assert summary["entry_events"] == 1
    assert summary["exit_events"] == 1
    assert summary["dwell_events"] == 1
    assert summary["estimated_conversion_rate"] == 1.0


def test_reject_empty_ingest_batch() -> None:
    response = client.post("/events/ingest", json=[])
    assert response.status_code == 400
