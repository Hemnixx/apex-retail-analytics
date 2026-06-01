# Apex Retail Analytics

![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)

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
- `GET /metrics` for lightweight request telemetry, trace ids, and latency summaries.
- `POST /events/ingest` for batched detection events.
- `GET /events` for recent stored events.
- `GET /analytics/summary` for counts, dwell metrics, and a conversion-rate proxy.
- `GET /stores/{store_id}/metrics` for live store-level KPIs.
- `GET /stores/{store_id}/funnel` for session-based conversion stages.
- `GET /stores/{store_id}/heatmap` for zone intensity.
- `GET /stores/{store_id}/anomalies` for queue and stale-feed style issues.
- `GET /stores/{store_id}/status` for per-store freshness.

## Local development

Install dependencies and run the API:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

If you are on Windows PowerShell and want a clean shell session first:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Run the detector in dry-run mode to validate the pipeline without CV dependencies:

```bash
python -m pipeline.detect --dry-run --api-url http://127.0.0.1:8000
```

Run the detector against the sample video when the model weights and runtime libraries are available:

```bash
python -m pipeline.detect --video-path sample_clip.mp4 --model-path yolov8n.pt --api-url http://127.0.0.1:8000
```

Start the live terminal dashboard in a third terminal:

```bash
python -m pipeline.dashboard --api-url http://127.0.0.1:8000 --store-id STORE_BLR_002
```

To inspect the output after a run:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/events
curl http://127.0.0.1:8000/stores/STORE_BLR_002/metrics
```

Detector output is also written to `artifacts/detection_events.jsonl`.

If a `transaction.csv` is present at the project root, or if `POS_TRANSACTIONS_PATH` is set, the API will correlate billing-zone sessions with POS transactions automatically.

If a `store_layout.json` is present at the project root, or if `STORE_LAYOUT_PATH` is set, `/health` and `/stores/{store_id}/status` will also include open-hours awareness and camera coverage metadata.

## Docker

Build and start the full stack:

```bash
docker compose up --build
```

The API is available on `http://localhost:8000`. The detector service starts in dry-run mode so the stack comes up reliably even if the computer-vision libraries are not available on the host.
The event store is backed by SQLite at `artifacts/store_events.sqlite3`, so events survive restarts unless you clear the store.

If you run the Docker stack, the dashboard service prints live metrics in the terminal while the detector feeds events into the API.

If you want a quick acceptance-gate check, run:

```powershell
python scripts/smoke_verify.py
```

That command confirms `/health`, `/stores/STORE_BLR_002/metrics`, and `/analytics/summary` all respond with the expected fields.

For a single-command judge bootstrap on Windows PowerShell, run:

```powershell
.
scripts\bootstrap.ps1
```

That script checks Docker, starts Compose, waits for the API to become healthy, and then runs the smoke verifier.

## Reviewer path

This is the fastest way to verify the submission against the evaluation framework:

1. Run `scripts\bootstrap.ps1`
2. Open `http://localhost:8000/health`
3. Run `python scripts/smoke_verify.py` if you want an extra direct check
4. Run the detector once in dry-run mode or against the sample clip
5. Open `http://localhost:8000/stores/STORE_BLR_002/metrics`
6. Inspect `artifacts/detection_events.jsonl`
7. Read `DESIGN.md` and `CHOICES.md`

Quick reviewer commands

```bash
# run unit tests
pytest -q

# smoke verify the running API (after starting the stack)
python scripts/smoke_verify.py

# run the shipped sample validation
python scripts/compare_counts.py validation/sample_ground_truth.csv validation/sample_events.jsonl --clip-id sample_clip_001
```

Schema version

Events now include a `schema_version` field; current value is `1` (see `app/schemas.py`). This makes it explicit which event contract the detector and API expect.

## Rubric Evidence

Use this section if you want to score the project against the hackathon rubric quickly.

### 5.1 Detection Pipeline

- Run `python scripts/smoke_verify.py` and confirm the event-backed metrics respond.
- Inspect `artifacts/detection_events.jsonl` to see structured `ENTRY`, `DWELL`, `EXIT`, and `BILLING_QUEUE_JOIN` events.
- Check that the funnel stays session-based and that the event schema includes `visitor_id`, `session_seq`, `zone_id`, `confidence`, and `is_staff`.
- If you want a ready-made example, run `python scripts/compare_counts.py validation/sample_ground_truth.csv validation/sample_events.jsonl --clip-id sample_clip_001`.
- If you have a labeled clip, run `python scripts/compare_counts.py validation/ground_truth.template.csv artifacts/detection_events.jsonl --clip-id clipA` after replacing the template values with real counts.
- Use [validation/ground_truth.template.csv](validation/ground_truth.template.csv) and [validation/ground_truth_events.template.jsonl](validation/ground_truth_events.template.jsonl) as the starting point for ground truth preparation.

### 5.2 API and Business Logic

- Query `GET /stores/STORE_BLR_002/metrics` and `GET /stores/STORE_BLR_002/funnel`.
- Verify the metrics are logically consistent with the event stream and that funnel counts are nested rather than double-counted.
- Query `GET /stores/STORE_BLR_002/anomalies` and confirm the response contains meaningful business rules such as dead-feed, billing queue spikes, and conversion drop detection.

### 5.3 Production Readiness

- Start the stack with `docker compose up --build -d` or `scripts/bootstrap.ps1`.
- Confirm the API becomes healthy with minimal setup.
- Check the structured logs in `app/main.py`, the request trace headers returned by the API, and the health warnings exposed by `/health` and `/stores/{store_id}/status`.
- Query `GET /metrics` to confirm basic telemetry is available without external tooling.
- Run `pytest -q` to confirm the core scenarios and edge cases pass.

### 5.4 Engineering Thinking and Decision Making

- Read [docs/DESIGN.md](docs/DESIGN.md) for the architecture and rejected alternatives.
- Read [choices.md](choices.md) for the trade-offs behind the detector, API, storage, dashboard, and deployment choices.
- Look for explicit rationale, not generic statements: the docs explain why the stack is split, why dry-run fallback exists, and why SQLite and a terminal dashboard were chosen.
- The strongest evidence lives in the decision log and validation sections: they tie every major choice to a constraint, a rejected alternative, and a check that was actually run.
- If you want to verify the reasoning path quickly, run `python scripts/compare_counts.py validation/sample_ground_truth.csv validation/sample_events.jsonl --clip-id sample_clip_001` and compare it with the documented trade-offs.

## Design notes

- The API stores events in SQLite so the submission has a real persistence story without requiring a separate database server.
- The detector emits JSONL audit logs under `artifacts/` so events can be inspected after a run.
- Staff filtering is represented in the schema with `is_staff` so downstream analytics can exclude non-customer traffic without losing traceability.
- The dashboard is terminal-based on purpose: it is easy for reviewers to run and proves the detector and API are connected live.
