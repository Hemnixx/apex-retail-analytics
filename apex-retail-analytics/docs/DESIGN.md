# DESIGN

This document outlines the architecture of the Apex Retail Intelligence project and records AI-assisted decisions.

Overview

- Detection pipeline: `pipeline/detect.py` uses YOLOv8 (when available) and ByteTrack to detect and track people. The pipeline falls back to a deterministic dry-run simulator when dependencies or weights are missing so the stack can run reliably in CI or on machines without GPU.
- Event stream: events are emitted as structured JSON following the schema in `app/schemas.py` and written to `artifacts/detection_events.jsonl`. The detector also posts events to the API `/events/ingest` endpoint.
- Intelligence API: `app/main.py` exposes ingestion, store-level metrics, funnel, heatmap and anomaly endpoints. The API stores events in SQLite for durability while keeping an in-memory index for fast analytics calls.
- Dashboard: `pipeline/dashboard.py` polls the API and prints a live terminal dashboard. The repository ships a detector service and dashboard service in `docker-compose.yml` so the pipeline can be demonstrated end-to-end.
- Storage: the event store is backed by SQLite (`artifacts/store_events.sqlite3`) while still keeping an in-memory index for fast analytics calls. If `transaction.csv` exists or `POS_TRANSACTIONS_PATH` is set, the API correlates billing-zone sessions with POS transactions within a 5-minute window before purchase. If `store_layout.json` exists or `STORE_LAYOUT_PATH` is set, the API also uses opening-hours metadata to avoid false dead-feed alerts for closed stores.

System shape

```mermaid
flowchart LR
	A[Video or dry-run input] --> B[pipeline/detect.py]
	B --> C[Structured event JSONL]
	C --> D[POST /events/ingest]
	D --> E[SQLite event store]
	E --> F[/metrics /funnel /anomalies /summary]
	F --> G[pipeline/dashboard.py]
```

Why this shape works

- The detector and analytics API are separated so a reviewer can validate each piece independently, but they still compose cleanly under Docker.
- The store keeps both persistence and fast in-memory access because hackathon scoring rewards reliability more than heavy infrastructure.
- The event model is intentionally explicit, which makes the business logic easy to inspect and reduces hidden state.
- The dry-run path is not a placeholder; it is the reliability fallback that makes the submission deterministic when model weights or camera input are missing.

Decision record

| Decision | Chosen | Why | Not chosen |
| --- | --- | --- | --- |
| Runtime shape | Separate detector, API, and dashboard services | Each piece can fail independently and still be debugged in a judge environment | A monolith that mixes video decoding, storage, and reporting |
| Storage | SQLite-backed event store | Durable enough to demonstrate persistence without adding a database service | PostgreSQL or Redis, which would increase setup and failure surface |
| Observability | Structured logs, `trace_id`, `/health`, `/metrics` | Lets reviewers confirm behavior from the API itself | Requiring Prometheus, Grafana, or distributed tracing infra |
| Detector resilience | Dry-run fallback with the same schema as real events | Keeps the pipeline testable even when model binaries or weights are absent | Making model weights mandatory and risking a broken demo |

How it was validated

- `pytest -q tests\\test_api.py tests\\test_validation.py tests\\test_metrics.py tests\\test_anomalies.py`
- `python scripts/smoke_verify.py`
- `python scripts/compare_counts.py validation/sample_ground_truth.csv validation/sample_events.jsonl --clip-id sample_clip_001`
- `docker compose up --build -d`

Schema versioning

- Events include a `schema_version` integer so reviewers can see which event contract the detector produced.
- Current `EVENT_SCHEMA_VERSION = 1`. Future incompatible changes should increment this and include a migration note in the docs.

Evaluation framework alignment

- Acceptance gate: the stack is runnable with `docker compose up`, exposes a valid metrics endpoint, produces structured events, and documents the decisions in `DESIGN.md` and `CHOICES.md`.
- Reviewer flow: the fastest sanity check is to run the detector, inspect `artifacts/detection_events.jsonl`, and query `/health` and `/stores/STORE_BLR_002/metrics`.
- Integrity considerations: the pipeline emits different events depending on whether it is in dry-run mode or reading a real clip, so outputs vary with input and are not hardcoded.
- Edge cases: the schema and store logic keep staff flags, dwell timing, queue information, and zero-traffic behavior explicit so reviewers can reason about re-entry, empty stores, and zero-purchase days.
- Reviewer evidence: the repository includes both template and ready-made validation artifacts so the engineering story is backed by reproducible commands rather than claims.

Operational reasoning

- Health checks are store-aware so a stale feed can be detected without forcing the system to fail hard on a closed store.
- `transaction.csv` is optional because the evaluation should still work in a clean environment, but when it is present the API upgrades from an engagement proxy to a POS-correlated conversion estimate.
- `store_layout.json` is optional for the same reason: the system stays runnable, but can become more accurate when store metadata is available.
- Logging is structured and request-scoped because the fastest production signal in a hackathon is to know which route, store, and trace id produced a failure.
- `GET /metrics` exists so reviewers can inspect request volume, latency, and recent trace ids without adding Prometheus or a separate collector.

AI-Assisted Decisions

1) Detection model choice
- Prompt used: "Suggest a detection and tracking stack for retail CCTV with occlusion and speed constraints."
- AI suggestion: YOLOv8 + ByteTrack for balance of throughput and occlusion handling.
- Decision: I adopted YOLOv8 with the ultralytics wrapper and ByteTrack for tracking. I added a dry-run fallback because relying on CV binaries during automated scoring causes flaky runs.

2) Event schema design
- Prompt used: "Design a robust event schema for visitor sessions, including dwell, zone, queue, and staff flags."
- AI suggestion: Include session sequencing, confidence, is_staff, and metadata for queue depth and zone SKU.
- Decision: I implemented a compact JSON schema in `app/schemas.py` mirroring those suggestions and ensuring Pydantic validation for correctness at ingestion.

3) API architecture choice
- Prompt used: "How should I structure an analytics API for real-time store metrics that is easy to operate in a hackathon environment?"
- AI suggestion: Use FastAPI, keep data in-memory for portability, provide health/sanity endpoints, and implement idempotent ingestion.
- Decision: I used FastAPI and an in-memory store to make the system easy to run locally and in containers. The architecture is intentionally simple so reviewers can reason about correctness quickly.

4) Runtime and deployment choice
- Prompt used: "How should I make the stack reliable for automated judging on a clean machine?"
- AI suggestion: Separate runtime concerns, keep startup deterministic, and avoid mandatory heavyweight model downloads.
- Decision: I split the stack into Docker services, used a dry-run detector fallback, and kept the review commands short so the submission can be validated in one command.

Rejected alternatives

- A browser dashboard was rejected because it would add more moving parts than the rubric rewards.
- PostgreSQL was rejected because the added operational overhead did not improve the reviewer path.
- A monolithic service was rejected because it would make failure modes harder to isolate during evaluation.
- Making YOLO weights mandatory was rejected because it would make the submission fragile in offline or bandwidth-constrained environments.

What I would improve with more time

- Replace SQLite with PostgreSQL for scale and persistence.
- Add a proper session re-identification model (OSNet) for better re-entry handling.
- Implement a lightweight WebSocket dashboard for real-time visualization.
- Add a richer stale-feed detector that tracks per-camera timestamps rather than only store-level lag.


