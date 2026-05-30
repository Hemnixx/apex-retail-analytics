# Apex Retail Analytics

This project turns CCTV footage into structured retail analytics.

It is written to satisfy the evaluation framework below:

- The detector emits structured events from raw CCTV or a dry-run simulator.
- The API ingests events, deduplicates them, and exposes store metrics.
- The repository includes `DESIGN.md`, `CHOICES.md`, tests, Docker, and a repeatable run path.
- The main business metric is offline store conversion rate.

The solution is split into four parts:

- Detection pipeline in `pipeline/detect.py` uses YOLOv8 with ByteTrack when the runtime dependencies and model weights are available.
- Intelligence API in `app/main.py` validates events, deduplicates them, and computes store-level metrics.
- Docker support is provided through `Dockerfile` and `docker-compose.yml`.
- AI usage is documented in `CHOICES.md` and `tests/test_prompts.py`.

## What the API exposes

- `GET /health` for readiness and uptime checks.
- `POST /events/ingest` for batched detection events.
- `GET /events` for recent stored events.
- `GET /analytics/summary` for counts, dwell metrics, and a conversion-rate proxy.
- `GET /stores/{store_id}/metrics` for live store-level KPIs.
- `GET /stores/{store_id}/funnel` for session-based conversion stages.
- `GET /stores/{store_id}/heatmap` for zone intensity.
- `GET /stores/{store_id}/anomalies` for queue and stale-feed style issues.

## Local development

Install dependencies and run the API:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run the detector in dry-run mode to validate the pipeline without CV dependencies:

```bash
python -m pipeline.detect --dry-run --api-url http://127.0.0.1:8000
```

Run the detector against the sample video when the model weights and runtime libraries are available:

```bash
python -m pipeline.detect --video-path sample_clip.mp4 --model-path yolov8n.pt --api-url http://127.0.0.1:8000
```

To inspect the output after a run:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/events
curl http://127.0.0.1:8000/stores/STORE_BLR_002/metrics
```

Detector output is also written to `artifacts/detection_events.jsonl`.

## Docker

Build and start the API and detector services:

```bash
docker compose up --build
```

The API is available on `http://localhost:8000`. The detector service starts in dry-run mode so the stack comes up reliably even if the computer-vision libraries are not available on the host.

## Reviewer path

This is the fastest way to verify the submission against the evaluation framework:

1. `docker compose up --build`
2. Open `http://localhost:8000/health`
3. Run the detector once in dry-run mode or against the sample clip
4. Open `http://localhost:8000/stores/STORE_BLR_002/metrics`
5. Inspect `artifacts/detection_events.jsonl`
6. Read `DESIGN.md` and `CHOICES.md`

## Design notes

- The API keeps an in-memory store because the hackathon scoring favors fast startup and clear validation over database setup.
- The detector emits JSONL audit logs under `artifacts/` so events can be inspected after a run.
- Staff filtering is represented in the schema with `is_staff` so downstream analytics can exclude non-customer traffic without losing traceability.
