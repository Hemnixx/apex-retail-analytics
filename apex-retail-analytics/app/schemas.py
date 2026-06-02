from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator


# Event schema versioning helps reviewers and future migrations
EVENT_SCHEMA_VERSION = 1


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = Field(ge=1)
    dwell_seconds: Optional[float] = Field(default=None, ge=0)
    source: Optional[str] = None


class RetailEvent(BaseModel):
    schema_version: int = Field(default=EVENT_SCHEMA_VERSION, ge=1)
    event_id: str
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = Field(default=0, ge=0)
    is_staff: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: EventMetadata

    @field_validator("event_type")
    def normalize_event_type(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("event_type cannot be empty")
        return normalized


class IngestResult(BaseModel):
    received: int
    ingested: int
    duplicates: int
    total_stored: int


class HealthResponse(BaseModel):
    status: str
    total_events_stored: int
    timestamp: datetime
    last_event_timestamp_by_store: Dict[str, Optional[datetime]]
    warnings: list[str]


class RequestMetricsResponse(BaseModel):
    uptime_seconds: float
    total_requests: int
    total_errors: int
    average_latency_ms: float
    max_latency_ms: int
    requests_by_path: Dict[str, int]
    status_codes: Dict[str, int]
    recent_trace_ids: list[str]


class StoreStatus(BaseModel):
    store_id: str
    last_event_timestamp: Optional[datetime] = None
    stale_feed: bool = False
    is_open: Optional[bool] = None
    opening_hours: Optional[object] = None
    camera_coverage: dict[str, list[str]] = Field(default_factory=dict)


class AnalyticsSummary(BaseModel):
    total_events: int
    unique_visitors: int
    entry_events: int
    exit_events: int
    dwell_events: int
    queue_spike_events: int
    active_sessions: int
    engaged_sessions: int
    staff_events: int
    average_dwell_ms: float
    estimated_conversion_rate: float
    conversion_basis: str


class FunnelStage(BaseModel):
    name: str
    count: int
    dropoff_pct: float


class FunnelResponse(BaseModel):
    entry_count: int
    zone_visit_count: int
    billing_queue_count: int
    purchase_count: int
    stages: list[FunnelStage]


class HeatmapZone(BaseModel):
    zone_id: str
    visits: int
    average_dwell_ms: float
    score: int


class HeatmapResponse(BaseModel):
    zones: list[HeatmapZone]
    data_confidence: bool


class Anomaly(BaseModel):
    anomaly_type: str
    severity: str
    message: str
    suggested_action: str


class AnomaliesResponse(BaseModel):
    anomalies: list[Anomaly]
