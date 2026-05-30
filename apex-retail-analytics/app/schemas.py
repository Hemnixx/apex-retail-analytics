from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = Field(ge=1)
    dwell_seconds: Optional[float] = Field(default=None, ge=0)
    source: Optional[str] = None


class RetailEvent(BaseModel):
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
