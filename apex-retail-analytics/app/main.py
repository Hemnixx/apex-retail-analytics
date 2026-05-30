from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import time
import uuid

from .schemas import AnalyticsSummary, HealthResponse, IngestResult, RetailEvent
from .store import STORE


app = FastAPI(title="Apex Retail Intelligence API")

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
    store_id = request.path_params.get("id") or request.query_params.get("store_id") or "-"
    event_count = getattr(response, "headers", {}).get("x-event-count", "-")
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


@app.get("/stores/{store_id}/funnel", response_model=dict)
async def store_funnel(store_id: str):
    return STORE.funnel(store_id)


@app.get("/stores/{store_id}/heatmap", response_model=dict)
async def store_heatmap(store_id: str):
    return STORE.heatmap(store_id)


@app.get("/stores/{store_id}/anomalies", response_model=dict)
async def store_anomalies(store_id: str):
    return STORE.anomalies(store_id)


@app.get("/analytics/summary", response_model=AnalyticsSummary)
async def analytics_summary() -> AnalyticsSummary:
    return STORE.summary()


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        total_events_stored=len(STORE.events),
        timestamp=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)