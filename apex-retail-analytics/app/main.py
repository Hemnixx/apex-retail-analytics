from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections import Counter, deque
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import time
import uuid

from .schemas import AnalyticsSummary, AnomaliesResponse, FunnelResponse, HealthResponse, HeatmapResponse, IngestResult, RequestMetricsResponse, RetailEvent, StoreStatus
from .store import STORE


app = FastAPI(title="Apex Retail Intelligence API")

APP_START = time.time()
REQUEST_PATH_COUNTS: Counter[str] = Counter()
REQUEST_STATUS_COUNTS: Counter[str] = Counter()
REQUEST_LATENCIES_MS: list[int] = []
RECENT_TRACE_IDS: deque[str] = deque(maxlen=20)

# basic structured logging
logger = logging.getLogger("app")
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


@app.middleware("http")
async def add_logging(request: Request, call_next):
    start = time.time()
    trace_id = str(uuid.uuid4())
    response = await call_next(request)
    latency_ms = int((time.time() - start) * 1000)
    store_id = request.path_params.get("store_id") or request.query_params.get("store_id") or "-"
    event_count = getattr(response, "headers", {}).get("x-event-count", "-")
    REQUEST_PATH_COUNTS[request.url.path] += 1
    REQUEST_STATUS_COUNTS[str(response.status_code)] += 1
    REQUEST_LATENCIES_MS.append(latency_ms)
    RECENT_TRACE_IDS.append(trace_id)
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Request-Latency-Ms"] = str(latency_ms)
    logger.info(
        {
            "trace_id": trace_id,
            "path": request.url.path,
            "method": request.method,
            "store_id": store_id,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "event_count": event_count,
        }
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request, _exc):
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.post("/events/ingest", response_model=IngestResult)
async def ingest_events(events: List[RetailEvent]) -> IngestResult:
    if not events:
        raise HTTPException(status_code=400, detail="At least one event is required")
    return STORE.ingest(events)


@app.get("/events", response_model=List[RetailEvent])
async def list_events(limit: int = 100) -> List[RetailEvent]:
    return STORE.recent_events(limit=limit)


@app.get("/stores/{store_id}/metrics", response_model=AnalyticsSummary)
async def store_metrics(store_id: str) -> AnalyticsSummary:
    return STORE.metrics(store_id)


@app.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
async def store_funnel(store_id: str):
    return STORE.funnel(store_id)


@app.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
async def store_heatmap(store_id: str):
    return STORE.heatmap(store_id)


@app.get("/stores/{store_id}/anomalies", response_model=AnomaliesResponse)
async def store_anomalies(store_id: str):
    return STORE.anomalies(store_id)


@app.get("/stores/{store_id}/status", response_model=StoreStatus)
async def store_status(store_id: str) -> StoreStatus:
    return StoreStatus(**STORE.store_status(store_id))


@app.get("/analytics/summary", response_model=AnalyticsSummary)
async def analytics_summary() -> AnalyticsSummary:
    return STORE.summary()


@app.get("/metrics", response_model=RequestMetricsResponse)
async def metrics() -> RequestMetricsResponse:
    request_count = len(REQUEST_LATENCIES_MS)
    average_latency = sum(REQUEST_LATENCIES_MS) / request_count if request_count else 0.0
    total_errors = sum(count for status, count in REQUEST_STATUS_COUNTS.items() if int(status) >= 400)
    return RequestMetricsResponse(
        uptime_seconds=round(time.time() - APP_START, 2),
        total_requests=request_count,
        total_errors=total_errors,
        average_latency_ms=round(average_latency, 2),
        max_latency_ms=max(REQUEST_LATENCIES_MS, default=0),
        requests_by_path=dict(sorted(REQUEST_PATH_COUNTS.items())),
        status_codes=dict(sorted(REQUEST_STATUS_COUNTS.items())),
        recent_trace_ids=list(RECENT_TRACE_IDS),
    )


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    last_event_timestamp_by_store = STORE.last_event_timestamps()
    warnings: list[str] = []
    for store_id, timestamp in last_event_timestamp_by_store.items():
        if timestamp is None:
            continue
        if datetime.now(timezone.utc) - timestamp > timedelta(minutes=10):
            warnings.append(f"{store_id}:STALE_FEED")
    return HealthResponse(
        status="healthy",
        total_events_stored=len(STORE.events),
        timestamp=datetime.now(timezone.utc),
        last_event_timestamp_by_store=last_event_timestamp_by_store,
        warnings=warnings,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)