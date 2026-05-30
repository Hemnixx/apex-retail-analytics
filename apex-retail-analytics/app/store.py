from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .schemas import AnalyticsSummary, IngestResult, RetailEvent


ENGAGEMENT_EVENTS = {"DWELL", "QUEUE_SPIKE", "PURCHASE"}
TERMINAL_EVENTS = {"EXIT", "PURCHASE"}


@dataclass
class EventStore:
    events: "OrderedDict[str, RetailEvent]" = field(default_factory=OrderedDict)

    def ingest(self, batch: Iterable[RetailEvent]) -> IngestResult:
        received = 0
        ingested = 0
        duplicates = 0

        for event in batch:
            received += 1
            if event.event_id in self.events:
                duplicates += 1
                continue
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

    def summary(self) -> AnalyticsSummary:
        all_events = list(self.events.values())
        non_staff_events = [event for event in all_events if not event.is_staff]

        by_visitor: Dict[str, List[RetailEvent]] = defaultdict(list)
        for event in sorted(non_staff_events, key=lambda item: item.timestamp):
            by_visitor[event.visitor_id].append(event)

        entry_events = [event for event in non_staff_events if event.event_type == "ENTRY"]
        exit_events = [event for event in non_staff_events if event.event_type == "EXIT"]
        dwell_events = [event for event in non_staff_events if event.event_type == "DWELL"]
        queue_spike_events = [event for event in non_staff_events if event.event_type == "QUEUE_SPIKE"]
        purchase_events = [event for event in non_staff_events if event.event_type == "PURCHASE"]

        engaged_sessions = 0
        active_sessions = 0
        for timeline in by_visitor.values():
            has_engagement = any(event.event_type in ENGAGEMENT_EVENTS for event in timeline)
            if has_engagement:
                engaged_sessions += 1
            if timeline and timeline[-1].event_type not in TERMINAL_EVENTS:
                active_sessions += 1

        if purchase_events:
            converted_visitors = {event.visitor_id for event in purchase_events}
            conversion_basis = "purchase"
            conversion_rate = len(converted_visitors) / max(1, len({event.visitor_id for event in entry_events}))
        else:
            conversion_basis = "engagement_proxy"
            conversion_rate = engaged_sessions / max(1, len({event.visitor_id for event in entry_events}))

        average_dwell_ms = (
            sum(event.dwell_ms for event in dwell_events) / len(dwell_events)
            if dwell_events
            else 0.0
        )

        return AnalyticsSummary(
            total_events=len(all_events),
            unique_visitors=len({event.visitor_id for event in non_staff_events}),
            entry_events=len(entry_events),
            exit_events=len(exit_events),
            dwell_events=len(dwell_events),
            queue_spike_events=len(queue_spike_events),
            active_sessions=active_sessions,
            engaged_sessions=engaged_sessions,
            staff_events=len(all_events) - len(non_staff_events),
            average_dwell_ms=average_dwell_ms,
            estimated_conversion_rate=conversion_rate,
            conversion_basis=conversion_basis,
        )

    def _events_for_store(self, store_id: str):
        return [e for e in self.events.values() if e.store_id == store_id]

    def metrics(self, store_id: str) -> AnalyticsSummary:
        all_events = list(self._events_for_store(store_id))
        non_staff_events = [event for event in all_events if not event.is_staff]

        by_visitor: Dict[str, List[RetailEvent]] = defaultdict(list)
        for event in sorted(non_staff_events, key=lambda item: item.timestamp):
            by_visitor[event.visitor_id].append(event)

        entry_events = [event for event in non_staff_events if event.event_type == "ENTRY"]
        exit_events = [event for event in non_staff_events if event.event_type == "EXIT"]
        dwell_events = [event for event in non_staff_events if event.event_type == "DWELL"]
        queue_spike_events = [event for event in non_staff_events if event.event_type == "BILLING_QUEUE_JOIN"]
        purchase_events = [event for event in non_staff_events if event.event_type == "PURCHASE"]

        engaged_sessions = 0
        active_sessions = 0
        for timeline in by_visitor.values():
            has_engagement = any(event.event_type in ENGAGEMENT_EVENTS for event in timeline)
            if has_engagement:
                engaged_sessions += 1
            if timeline and timeline[-1].event_type not in TERMINAL_EVENTS:
                active_sessions += 1

        if purchase_events:
            converted_visitors = {event.visitor_id for event in purchase_events}
            conversion_basis = "purchase"
            conversion_rate = len(converted_visitors) / max(1, len({event.visitor_id for event in entry_events}))
        else:
            conversion_basis = "engagement_proxy"
            conversion_rate = engaged_sessions / max(1, len({event.visitor_id for event in entry_events}))

        average_dwell_ms = (
            sum(event.dwell_ms for event in dwell_events) / len(dwell_events)
            if dwell_events
            else 0.0
        )

        return AnalyticsSummary(
            total_events=len(all_events),
            unique_visitors=len({event.visitor_id for event in non_staff_events}),
            entry_events=len(entry_events),
            exit_events=len(exit_events),
            dwell_events=len(dwell_events),
            queue_spike_events=len(queue_spike_events),
            active_sessions=active_sessions,
            engaged_sessions=engaged_sessions,
            staff_events=len(all_events) - len(non_staff_events),
            average_dwell_ms=average_dwell_ms,
            estimated_conversion_rate=conversion_rate,
            conversion_basis=conversion_basis,
        )

    def funnel(self, store_id: str) -> dict:
        events = list(self._events_for_store(store_id))
        non_staff = [e for e in events if not e.is_staff]
        entry_visitors = {e.visitor_id for e in non_staff if e.event_type == "ENTRY"}
        zone_visit_visitors = {e.visitor_id for e in non_staff if e.event_type in {"ZONE_ENTER","DWELL"}}
        billing_visitors = {e.visitor_id for e in non_staff if e.event_type == "BILLING_QUEUE_JOIN" or (e.zone_id and e.zone_id.upper() == "CHECKOUT")}
        purchase_visitors = {e.visitor_id for e in non_staff if e.event_type == "PURCHASE"}

        entry_count = len(entry_visitors)
        zone_visit_count = len(zone_visit_visitors)
        billing_queue_count = len(billing_visitors)
        purchase_count = len(purchase_visitors)

        stages = []
        def pct(part, whole):
            return round(100.0 * (1 - (part / max(1, whole))), 2)

        stages.append({"name": "Entry", "count": entry_count, "dropoff_pct": pct(entry_count - zone_visit_count, entry_count)})
        stages.append({"name": "Zone Visit", "count": zone_visit_count, "dropoff_pct": pct(zone_visit_count - billing_queue_count, entry_count)})
        stages.append({"name": "Billing Queue", "count": billing_queue_count, "dropoff_pct": pct(billing_queue_count - purchase_count, entry_count)})
        stages.append({"name": "Purchase", "count": purchase_count, "dropoff_pct": 0.0})

        return {
            "entry_count": entry_count,
            "zone_visit_count": zone_visit_count,
            "billing_queue_count": billing_queue_count,
            "purchase_count": purchase_count,
            "stages": stages,
        }

    def heatmap(self, store_id: str) -> dict:
        events = list(self._events_for_store(store_id))
        non_staff = [e for e in events if not e.is_staff]
        zone_buckets: Dict[str, List[RetailEvent]] = defaultdict(list)
        for e in non_staff:
            if e.zone_id:
                zone_buckets[e.zone_id].append(e)

        zones = []
        max_visits = max((len(v) for v in zone_buckets.values()), default=0)
        for zone_id, bucket in zone_buckets.items():
            visits = len(bucket)
            avg_dwell = sum(e.dwell_ms for e in bucket) / visits if visits else 0.0
            score = int((visits / max(1, max_visits)) * 100) if max_visits > 0 else 0
            zones.append({"zone_id": zone_id, "visits": visits, "average_dwell_ms": avg_dwell, "score": score})

        data_confidence = len({e.visitor_id for e in non_staff}) >= 20
        return {"zones": zones, "data_confidence": data_confidence}

    def anomalies(self, store_id: str) -> dict:
        events = list(self._events_for_store(store_id))
        non_staff = [e for e in events if not e.is_staff]
        anomalies = []
        # Dead zone: no visits in last 30 minutes
        if non_staff:
            latest = max(e.timestamp for e in non_staff)
            from datetime import datetime, timezone, timedelta

            if datetime.now(timezone.utc) - latest > timedelta(minutes=30):
                anomalies.append({
                    "anomaly_type": "DEAD_ZONE",
                    "severity": "WARN",
                    "message": "No visits recorded in the last 30 minutes",
                    "suggested_action": "Check camera feed or staffing",
                })

        # Simple queue spike heuristic
        billing_joins = [e for e in non_staff if e.event_type == "BILLING_QUEUE_JOIN"]
        if len(billing_joins) >= 5:
            anomalies.append({
                "anomaly_type": "BILLING_QUEUE_SPIKE",
                "severity": "WARN",
                "message": f"Billing queue joins high: {len(billing_joins)}",
                "suggested_action": "Consider opening additional registers",
            })

        return {"anomalies": anomalies}


STORE = EventStore()
