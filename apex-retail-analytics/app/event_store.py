from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .schemas import AnalyticsSummary, Anomaly, AnomaliesResponse, FunnelResponse, FunnelStage, HeatmapResponse, HeatmapZone, IngestResult, RetailEvent


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = Path(os.getenv("STORE_DB_PATH", PROJECT_ROOT / "artifacts" / "store_events.sqlite3"))
SESSION_GAP = timedelta(minutes=5)
FRESHNESS_WINDOW = timedelta(minutes=10)
DEAD_ZONE_WINDOW = timedelta(minutes=30)
QUEUE_SPIKE_WINDOW = timedelta(minutes=10)
ENTRY_TYPES = {"ENTRY", "REENTRY"}
DWELL_TYPES = {"DWELL", "ZONE_DWELL"}
BILLING_TYPES = {"BILLING_QUEUE_JOIN"}
PURCHASE_TYPES = {"PURCHASE"}
TERMINAL_TYPES = {"EXIT", "PURCHASE", "BILLING_QUEUE_ABANDON"}
ZONE_TYPES = {"ZONE_ENTER", "ZONE_EXIT", "DWELL", "ZONE_DWELL", "BILLING_QUEUE_JOIN"}


@dataclass
class POSTransaction:
    store_id: str
    transaction_id: str
    timestamp: datetime
    basket_value: float


@dataclass
class StoreLayout:
    store_id: str
    zone_ids: List[str] = field(default_factory=list)
    camera_coverage: Dict[str, List[str]] = field(default_factory=dict)
    opening_hours: Any = None


@dataclass
class SessionRecord:
    store_id: str
    visitor_id: str
    events: List[RetailEvent]
    started_at: datetime
    ended_at: datetime
    session_index: int
    is_staff: bool = False

    @property
    def entry_event(self) -> Optional[RetailEvent]:
        return self.events[0] if self.events else None

    @property
    def final_event(self) -> Optional[RetailEvent]:
        return self.events[-1] if self.events else None

    @property
    def has_entry(self) -> bool:
        return any(event.event_type in ENTRY_TYPES for event in self.events)

    @property
    def has_zone_activity(self) -> bool:
        return any(event.event_type in ZONE_TYPES for event in self.events)

    @property
    def has_billing_queue(self) -> bool:
        return any(event.event_type in BILLING_TYPES for event in self.events)

    @property
    def has_purchase(self) -> bool:
        return any(event.event_type in PURCHASE_TYPES for event in self.events)

    @property
    def has_dwell(self) -> bool:
        return any(event.event_type in DWELL_TYPES for event in self.events)

    @property
    def active(self) -> bool:
        if not self.final_event:
            return False
        return self.final_event.event_type not in TERMINAL_TYPES

    @property
    def average_dwell_ms(self) -> float:
        dwell_events = [event.dwell_ms for event in self.events if event.event_type in DWELL_TYPES]
        return sum(dwell_events) / len(dwell_events) if dwell_events else 0.0


@dataclass
class EventStore:
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    pos_transactions_path: Optional[Path] = None
    store_layout_path: Optional[Path] = None
    events: "OrderedDict[str, RetailEvent]" = field(default_factory=OrderedDict)
    transactions: List[POSTransaction] = field(default_factory=list)
    store_layouts: Dict[str, StoreLayout] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.pos_transactions_path = self._resolve_pos_transactions_path(self.pos_transactions_path)
        self.store_layout_path = self._resolve_store_layout_path(self.store_layout_path)
        self._initialize_db()
        self._load_existing()
        self._load_transactions()
        self._load_store_layouts()

    def _resolve_pos_transactions_path(self, configured_path: Optional[Path]) -> Optional[Path]:
        if configured_path is not None:
            return Path(configured_path)

        env_path = os.getenv("POS_TRANSACTIONS_PATH")
        if env_path:
            return Path(env_path)

        candidates = [PROJECT_ROOT / "transaction.csv", PROJECT_ROOT / "artifacts" / "pos_transactions.csv"]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _resolve_store_layout_path(self, configured_path: Optional[Path]) -> Optional[Path]:
        if configured_path is not None:
            return Path(configured_path)

        env_path = os.getenv("STORE_LAYOUT_PATH")
        if env_path:
            return Path(env_path)

        candidates = [PROJECT_ROOT / "store_layout.json", PROJECT_ROOT / "artifacts" / "store_layout.json"]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_events_store_timestamp ON events(store_id, timestamp)")

    def _load_existing(self) -> None:
        self.events.clear()
        with self._connect() as connection:
            rows = connection.execute("SELECT event_id, payload FROM events ORDER BY timestamp ASC, rowid ASC").fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            event = RetailEvent.model_validate(payload)
            self.events[event.event_id] = event

    def _load_transactions(self) -> None:
        self.transactions = []
        if self.pos_transactions_path is None or not self.pos_transactions_path.exists():
            return

        with self.pos_transactions_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    timestamp = datetime.fromisoformat(str(row.get("timestamp", "")).replace("Z", "+00:00"))
                    self.transactions.append(
                        POSTransaction(
                            store_id=str(row.get("store_id", "")).strip(),
                            transaction_id=str(row.get("transaction_id", "")).strip(),
                            timestamp=timestamp,
                            basket_value=float(row.get("basket_value_inr") or row.get("basket_value") or 0.0),
                        )
                    )
                except Exception:
                    continue
        self.transactions.sort(key=lambda item: item.timestamp)

    def _load_store_layouts(self) -> None:
        self.store_layouts = {}
        if self.store_layout_path is None or not self.store_layout_path.exists():
            return

        try:
            payload = json.loads(self.store_layout_path.read_text(encoding="utf-8"))
        except Exception:
            return

        entries = payload if isinstance(payload, list) else payload.get("stores", payload)
        if isinstance(entries, dict):
            iterable = entries.values()
        else:
            iterable = entries if isinstance(entries, list) else []

        for entry in iterable:
            if not isinstance(entry, dict):
                continue
            store_id = str(entry.get("store_id") or entry.get("id") or "").strip()
            if not store_id:
                continue
            zone_ids = []
            zones = entry.get("zones") or entry.get("zone_ids") or []
            if isinstance(zones, list):
                for zone in zones:
                    if isinstance(zone, dict):
                        zone_name = str(zone.get("zone_id") or zone.get("name") or "").strip()
                        if zone_name:
                            zone_ids.append(zone_name)
                    else:
                        zone_name = str(zone).strip()
                        if zone_name:
                            zone_ids.append(zone_name)
            camera_coverage: Dict[str, List[str]] = {}
            coverage = entry.get("camera_coverage") or entry.get("cameras") or {}
            if isinstance(coverage, dict):
                for camera_id, zones_for_camera in coverage.items():
                    if isinstance(zones_for_camera, list):
                        camera_coverage[str(camera_id)] = [str(zone).strip() for zone in zones_for_camera if str(zone).strip()]
                    else:
                        camera_coverage[str(camera_id)] = [str(zones_for_camera).strip()]
            opening_hours = entry.get("opening_hours") or entry.get("hours")
            self.store_layouts[store_id] = StoreLayout(
                store_id=store_id,
                zone_ids=zone_ids,
                camera_coverage=camera_coverage,
                opening_hours=opening_hours,
            )

    def _opening_window_today(self, opening_hours: Any) -> Optional[tuple[datetime, datetime]]:
        if isinstance(opening_hours, dict):
            start_value = opening_hours.get("start") or opening_hours.get("open")
            end_value = opening_hours.get("end") or opening_hours.get("close")
        elif isinstance(opening_hours, str) and "-" in opening_hours:
            start_value, end_value = opening_hours.split("-", 1)
        else:
            return None

        try:
            now = datetime.now(timezone.utc)
            start_hour, start_minute = [int(part) for part in str(start_value).split(":", 1)]
            end_hour, end_minute = [int(part) for part in str(end_value).split(":", 1)]
            start = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            end = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
            if end <= start:
                end += timedelta(days=1)
            return start, end
        except Exception:
            return None

    def is_store_open(self, store_id: str, at: Optional[datetime] = None) -> Optional[bool]:
        layout = self.store_layouts.get(store_id)
        if layout is None or layout.opening_hours is None:
            return None
        window = self._opening_window_today(layout.opening_hours)
        if window is None:
            return None
        current_time = at or datetime.now(timezone.utc)
        return window[0] <= current_time <= window[1]

    def clear(self) -> None:
        self.events.clear()
        with self._connect() as connection:
            connection.execute("DELETE FROM events")

    def ingest(self, batch: Iterable[RetailEvent]) -> IngestResult:
        received = 0
        ingested = 0
        duplicates = 0

        with self._connect() as connection:
            for event in batch:
                received += 1
                if event.event_id in self.events:
                    duplicates += 1
                    continue
                serialized = json.dumps(event.model_dump(mode="json"), sort_keys=True)
                connection.execute(
                    "INSERT OR IGNORE INTO events (event_id, store_id, timestamp, payload) VALUES (?, ?, ?, ?)",
                    (event.event_id, event.store_id, event.timestamp.isoformat(), serialized),
                )
                self.events[event.event_id] = event
                ingested += 1

        return IngestResult(
            received=received,
            ingested=ingested,
            duplicates=duplicates,
            total_stored=len(self.events),
        )

    def recent_events(self, limit: int = 100) -> List[RetailEvent]:
        if limit <= 0:
            return []
        return list(self.events.values())[-limit:]

    def _events_for_store(self, store_id: str) -> List[RetailEvent]:
        return [event for event in self.events.values() if event.store_id == store_id]

    def _group_sessions(self, events: List[RetailEvent]) -> List[SessionRecord]:
        sessions: List[SessionRecord] = []
        by_store_and_visitor: Dict[tuple[str, str], List[RetailEvent]] = defaultdict(list)
        for event in sorted(events, key=lambda item: item.timestamp):
            by_store_and_visitor[(event.store_id, event.visitor_id)].append(event)

        for (store_id, visitor_id), timeline in by_store_and_visitor.items():
            current_events: List[RetailEvent] = []
            session_index = 0
            for event in timeline:
                should_split = False
                if current_events:
                    gap = event.timestamp - current_events[-1].timestamp
                    previous_terminal = current_events[-1].event_type in TERMINAL_TYPES
                    next_entry = event.event_type in ENTRY_TYPES
                    should_split = gap > SESSION_GAP or (next_entry and previous_terminal)

                if should_split and current_events:
                    session_index += 1
                    sessions.append(
                        SessionRecord(
                            store_id=store_id,
                            visitor_id=visitor_id,
                            events=current_events,
                            started_at=current_events[0].timestamp,
                            ended_at=current_events[-1].timestamp,
                            session_index=session_index,
                            is_staff=any(item.is_staff for item in current_events),
                        )
                    )
                    current_events = []

                current_events.append(event)

            if current_events:
                session_index += 1
                sessions.append(
                    SessionRecord(
                        store_id=store_id,
                        visitor_id=visitor_id,
                        events=current_events,
                        started_at=current_events[0].timestamp,
                        ended_at=current_events[-1].timestamp,
                        session_index=session_index,
                        is_staff=any(item.is_staff for item in current_events),
                    )
                )
        return sessions

    def _sessions_for_store(self, store_id: str, events: Optional[List[RetailEvent]] = None) -> List[SessionRecord]:
        source_events = events if events is not None else self._events_for_store(store_id)
        return [session for session in self._group_sessions(source_events) if session.store_id == store_id]

    def _correlate_transactions(self, sessions: List[SessionRecord], store_id: Optional[str] = None) -> set[tuple[str, str, int]]:
        eligible_transactions = [txn for txn in self.transactions if store_id is None or txn.store_id == store_id]
        converted_sessions: set[tuple[str, str, int]] = set()

        if not eligible_transactions:
            return converted_sessions

        for transaction in eligible_transactions:
            candidate_session: Optional[SessionRecord] = None
            candidate_gap: Optional[timedelta] = None
            for session in sessions:
                if session.store_id != transaction.store_id:
                    continue
                billing_timestamps = [
                    event.timestamp
                    for event in session.events
                    if event.event_type in BILLING_TYPES or (event.zone_id and event.zone_id.upper() == "CHECKOUT")
                ]
                if not billing_timestamps:
                    continue
                latest_billing_timestamp = max(billing_timestamps)
                if latest_billing_timestamp > transaction.timestamp:
                    continue
                gap = transaction.timestamp - latest_billing_timestamp
                if gap > timedelta(minutes=5):
                    continue
                if candidate_gap is None or gap < candidate_gap:
                    candidate_session = session
                    candidate_gap = gap
            if candidate_session is not None:
                converted_sessions.add((candidate_session.store_id, candidate_session.visitor_id, candidate_session.session_index))

        return converted_sessions

    def _summary_from_events(self, events: List[RetailEvent]) -> AnalyticsSummary:
        non_staff_events = [event for event in events if not event.is_staff]
        sessions = self._group_sessions(non_staff_events)
        converted_sessions = self._correlate_transactions(sessions)

        entry_events = [event for event in non_staff_events if event.event_type in ENTRY_TYPES]
        exit_events = [event for event in non_staff_events if event.event_type == "EXIT"]
        dwell_events = [event for event in non_staff_events if event.event_type in DWELL_TYPES]
        queue_spike_events = [event for event in non_staff_events if event.event_type in BILLING_TYPES]

        engaged_sessions = sum(1 for session in sessions if session.has_zone_activity or session.has_dwell or session.has_billing_queue)
        active_sessions = sum(1 for session in sessions if session.active)
        session_entry_count = sum(1 for session in sessions if session.has_entry)
        if converted_sessions:
            conversion_basis = "pos_correlated"
            conversion_rate = len(converted_sessions) / max(1, session_entry_count)
        elif any(session.has_purchase for session in sessions):
            conversion_basis = "event_purchase_fallback"
            conversion_rate = sum(1 for session in sessions if session.has_purchase) / max(1, session_entry_count)
        else:
            conversion_basis = "engagement_proxy"
            conversion_rate = engaged_sessions / max(1, session_entry_count)

        average_dwell_ms = (
            sum(event.dwell_ms for event in dwell_events) / len(dwell_events)
            if dwell_events
            else 0.0
        )

        return AnalyticsSummary(
            total_events=len(events),
            unique_visitors=len({event.visitor_id for event in non_staff_events}),
            entry_events=len(entry_events),
            exit_events=len(exit_events),
            dwell_events=len(dwell_events),
            queue_spike_events=len(queue_spike_events),
            active_sessions=active_sessions,
            engaged_sessions=engaged_sessions,
            staff_events=len(events) - len(non_staff_events),
            average_dwell_ms=average_dwell_ms,
            estimated_conversion_rate=min(1.0, conversion_rate),
            conversion_basis=conversion_basis,
        )

    def summary(self) -> AnalyticsSummary:
        return self._summary_from_events(list(self.events.values()))

    def metrics(self, store_id: str) -> AnalyticsSummary:
        return self._summary_from_events(self._events_for_store(store_id))

    def funnel(self, store_id: str) -> FunnelResponse:
        sessions = self._sessions_for_store(store_id, [event for event in self._events_for_store(store_id) if not event.is_staff])
        converted_sessions = self._correlate_transactions(sessions, store_id=store_id)
        entry_sessions = [session for session in sessions if session.has_entry]

        def session_key(session: SessionRecord) -> tuple[str, str, int]:
            return (session.store_id, session.visitor_id, session.session_index)

        zone_visit_sessions = [
            session
            for session in entry_sessions
            if session.has_zone_activity or session.has_dwell or session.has_billing_queue
        ]
        billing_queue_sessions = [session for session in zone_visit_sessions if session.has_billing_queue]
        purchase_sessions = [
            session
            for session in billing_queue_sessions
            if session.has_purchase or session_key(session) in converted_sessions
        ]

        entry_count = len(entry_sessions)
        zone_visit_count = len(zone_visit_sessions)
        billing_queue_count = len(billing_queue_sessions)
        purchase_count = len(purchase_sessions)

        def dropoff(previous: int, current: int) -> float:
            if previous <= 0:
                return 0.0
            retained = min(current, previous)
            return round(100.0 * (1 - retained / previous), 2)

        stages = [
            FunnelStage(name="Entry", count=entry_count, dropoff_pct=dropoff(entry_count, zone_visit_count)),
            FunnelStage(name="Zone Visit", count=zone_visit_count, dropoff_pct=dropoff(zone_visit_count, billing_queue_count)),
            FunnelStage(name="Billing Queue", count=billing_queue_count, dropoff_pct=dropoff(billing_queue_count, purchase_count)),
            FunnelStage(name="Purchase", count=purchase_count, dropoff_pct=0.0),
        ]
        return FunnelResponse(
            entry_count=entry_count,
            zone_visit_count=zone_visit_count,
            billing_queue_count=billing_queue_count,
            purchase_count=purchase_count,
            stages=stages,
        )

    def heatmap(self, store_id: str) -> HeatmapResponse:
        non_staff = [event for event in self._events_for_store(store_id) if not event.is_staff]
        sessions = self._sessions_for_store(store_id, non_staff)
        zone_buckets: Dict[str, List[RetailEvent]] = defaultdict(list)
        for event in non_staff:
            if event.zone_id:
                zone_buckets[event.zone_id].append(event)

        max_visits = max((len(bucket) for bucket in zone_buckets.values()), default=0)
        zones: List[HeatmapZone] = []
        for zone_id, bucket in zone_buckets.items():
            visits = len(bucket)
            dwell_ms = sum(event.dwell_ms for event in bucket if event.event_type in DWELL_TYPES)
            avg_dwell = dwell_ms / max(1, sum(1 for event in bucket if event.event_type in DWELL_TYPES))
            score = int((visits / max(1, max_visits)) * 100) if max_visits else 0
            zones.append(HeatmapZone(zone_id=zone_id, visits=visits, average_dwell_ms=avg_dwell, score=score))

        return HeatmapResponse(zones=zones, data_confidence=len(sessions) >= 20)

    def anomalies(self, store_id: str) -> AnomaliesResponse:
        events = [event for event in self._events_for_store(store_id) if not event.is_staff]
        sessions = self._sessions_for_store(store_id, events)
        converted_sessions = self._correlate_transactions(sessions, store_id=store_id)
        anomalies: List[Anomaly] = []
        layout = self.store_layouts.get(store_id)
        store_is_open = self.is_store_open(store_id)

        latest_timestamp = max((event.timestamp for event in events), default=None)
        now = datetime.now(timezone.utc)

        if latest_timestamp is None:
            anomalies.append(
                Anomaly(
                    anomaly_type="DEAD_ZONE",
                    severity="WARN",
                    message="No customer events recorded yet",
                    suggested_action="Check that the feed is connected and generating events",
                )
            )
            return AnomaliesResponse(anomalies=anomalies)

        if store_is_open is not False and now - latest_timestamp > DEAD_ZONE_WINDOW:
            anomalies.append(
                Anomaly(
                    anomaly_type="DEAD_ZONE",
                    severity="WARN",
                    message="No visits recorded in the last 30 minutes",
                    suggested_action="Check camera feed or staffing",
                )
            )

        recent_queue_joins = [
            event for event in events if event.event_type in BILLING_TYPES and now - event.timestamp <= QUEUE_SPIKE_WINDOW
        ]
        if len(recent_queue_joins) >= 3:
            anomalies.append(
                Anomaly(
                    anomaly_type="BILLING_QUEUE_SPIKE",
                    severity="WARN",
                    message=f"Billing queue joins high in the last 10 minutes: {len(recent_queue_joins)}",
                    suggested_action="Open an additional register or re-route staff to the billing counter",
                )
            )

        entry_sessions = [session for session in sessions if session.has_entry]
        terminal_sessions = [session for session in entry_sessions if not session.active]
        if len(entry_sessions) >= 8:
            completion_rate = len(terminal_sessions) / max(1, len(entry_sessions))
            if completion_rate < 0.5:
                anomalies.append(
                    Anomaly(
                        anomaly_type="ENTRY_EXIT_IMBALANCE",
                        severity="WARN" if completion_rate > 0.25 else "CRITICAL",
                        message=f"Only {len(terminal_sessions)} of {len(entry_sessions)} entry sessions reached a terminal state",
                        suggested_action="Check for stuck sessions, camera gaps, or missing exit events",
                    )
                )

        if len(sessions) >= 10:
            overall_purchase_rate = len(converted_sessions) / max(1, sum(1 for session in sessions if session.has_entry)) if converted_sessions else sum(1 for session in sessions if session.has_purchase) / max(1, sum(1 for session in sessions if session.has_entry))
            recent_sessions = sessions[-10:]
            recent_keys = {(session.store_id, session.visitor_id, session.session_index) for session in recent_sessions}
            recent_purchase_rate = len(recent_keys & converted_sessions) / max(1, sum(1 for session in recent_sessions if session.has_entry)) if converted_sessions else sum(1 for session in recent_sessions if session.has_purchase) / max(1, sum(1 for session in recent_sessions if session.has_entry))
            if overall_purchase_rate > 0 and recent_purchase_rate < max(0.2, overall_purchase_rate * 0.5):
                anomalies.append(
                    Anomaly(
                        anomaly_type="CONVERSION_DROP",
                        severity="WARN" if recent_purchase_rate > 0 else "CRITICAL",
                        message="Recent conversion rate is below the historical baseline",
                        suggested_action="Inspect queueing, promotions, and staffing at the billing zone",
                    )
                )

        return AnomaliesResponse(anomalies=anomalies)

    def last_event_timestamps(self) -> Dict[str, Optional[datetime]]:
        timestamps: Dict[str, Optional[datetime]] = {}
        for event in self.events.values():
            current = timestamps.get(event.store_id)
            if current is None or event.timestamp > current:
                timestamps[event.store_id] = event.timestamp
        return timestamps

    def store_status(self, store_id: str) -> dict:
        latest = max((event.timestamp for event in self._events_for_store(store_id)), default=None)
        stale_feed = latest is not None and datetime.now(timezone.utc) - latest > FRESHNESS_WINDOW
        layout = self.store_layouts.get(store_id)
        return {
            "store_id": store_id,
            "last_event_timestamp": latest,
            "stale_feed": stale_feed,
            "is_open": self.is_store_open(store_id),
            "opening_hours": layout.opening_hours if layout else None,
            "camera_coverage": layout.camera_coverage if layout else {},
        }


STORE = EventStore()
