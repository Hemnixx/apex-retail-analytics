from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VIDEO = PROJECT_ROOT / "sample_clip.mp4"
DEFAULT_MODEL = PROJECT_ROOT / "yolov8n.pt"
DEFAULT_LOG = PROJECT_ROOT / "artifacts" / "detection_events.jsonl"


@dataclass
class TrackSession:
    visitor_id: str
    first_seen_frame: int
    last_seen_frame: int
    event_seq: int = 0
    entry_emitted: bool = False
    exit_emitted: bool = False
    last_dwell_frame: int = 0
    current_zone: str = "MAIN_FLOOR"
    is_staff: bool = False
    zone_history: List[str] = field(default_factory=list)
    has_billing_queue: bool = False
    last_visible_frame: int = 0
    last_center_x: float = 0.0
    reentry_count: int = 0


@dataclass
class RecentExit:
    visitor_id: str
    frame_index: int
    zone_id: str
    center_x: float


STAFF_ZONE_THRESHOLD = 3
REENTRY_WINDOW_FRAMES = 90
QUEUE_ZONE = "CHECKOUT"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def build_event_payload(
    *,
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    session_seq: int,
    zone_id: Optional[str] = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 1.0,
    queue_depth: Optional[int] = None,
    sku_zone: Optional[str] = None,
    source: str = "pipeline.detect",
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type.strip().upper(),
        "timestamp": utc_iso(),
        "zone_id": zone_id,
        "dwell_ms": max(0, int(dwell_ms)),
        "is_staff": is_staff,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": sku_zone or zone_id,
            "session_seq": max(1, int(session_seq)),
            "dwell_seconds": round(max(0, int(dwell_ms)) / 1000.0, 3),
            "source": source,
        },
    }


def write_events(log_path: Path, events: Sequence[dict]) -> None:
    if not events:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True))
            handle.write("\n")


def post_events(api_url: str, events: Sequence[dict]) -> None:
    if not api_url or not events:
        return
    payload = json.dumps(list(events)).encode("utf-8")
    request = urlrequest.Request(
        api_url.rstrip("/") + "/events/ingest",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(request, timeout=10) as response:
            response.read()
    except urlerror.URLError as exc:
        print(f"[pipeline] API ingest failed: {exc}")


def _simulate_events(store_id: str, camera_id: str) -> List[dict]:
    events = []
    visitor_plan = [
        ("VIS_A", 1, 45000),
        ("VIS_B", 2, 120000),
        ("VIS_C", 3, 90000),
    ]
    for visitor_id, session_seq, dwell_ms in visitor_plan:
        events.append(
            build_event_payload(
                store_id=store_id,
                camera_id=camera_id,
                visitor_id=visitor_id,
                event_type="ENTRY",
                session_seq=session_seq,
                zone_id="ENTRANCE",
                source="pipeline.detect.mock",
            )
        )
        events.append(
            build_event_payload(
                store_id=store_id,
                camera_id=camera_id,
                visitor_id=visitor_id,
                event_type="DWELL",
                session_seq=session_seq + 1,
                zone_id="AISLE_A",
                dwell_ms=dwell_ms,
                confidence=0.95,
                source="pipeline.detect.mock",
            )
        )
        events.append(
            build_event_payload(
                store_id=store_id,
                camera_id=camera_id,
                visitor_id=visitor_id,
                event_type="EXIT",
                session_seq=session_seq + 2,
                zone_id="EXIT",
                source="pipeline.detect.mock",
            )
        )
    return events


def _classify_zone(center_x: float, frame_width: float) -> str:
    if frame_width <= 0:
        return "MAIN_FLOOR"
    if center_x < frame_width * 0.33:
        return "ENTRY_ZONE"
    if center_x < frame_width * 0.66:
        return "MAIN_FLOOR"
    return "CHECKOUT"


def _match_recent_exit(recent_exits: Sequence[RecentExit], zone_id: str, frame_index: int) -> Optional[RecentExit]:
    for exit_record in reversed(recent_exits):
        if frame_index - exit_record.frame_index > REENTRY_WINDOW_FRAMES:
            continue
        if exit_record.zone_id == zone_id or exit_record.zone_id == "EXIT" or zone_id == "ENTRY_ZONE":
            return exit_record
    return None


def _estimate_queue_depth(visible_tracks: Sequence[Tuple[int, Tuple[float, float, float, float], float]], frame_width: float) -> int:
    if frame_width <= 0:
        return 0
    checkout_tracks = 0
    for _track_id, coordinates, _confidence in visible_tracks:
        x1, _y1, x2, _y2 = coordinates
        center_x = (x1 + x2) / 2.0
        if _classify_zone(center_x, frame_width) == QUEUE_ZONE:
            checkout_tracks += 1
    return max(0, checkout_tracks - 1)


def _load_runtime_dependencies():
    try:
        import cv2  # type: ignore
        from ultralytics import YOLO  # type: ignore
    except Exception:
        return None, None
    return cv2, YOLO


def _extract_tracks(result) -> List[Tuple[int, Tuple[float, float, float, float], float]]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or getattr(boxes, "id", None) is None:
        return []

    track_ids = boxes.id.cpu().numpy().astype(int).tolist()
    coordinates = boxes.xyxy.cpu().numpy().tolist()
    confidences = boxes.conf.cpu().numpy().tolist() if getattr(boxes, "conf", None) is not None else [1.0] * len(track_ids)
    return [
        (track_id, tuple(coordinate), float(confidence))
        for track_id, coordinate, confidence in zip(track_ids, coordinates, confidences)
    ]


def _run_real_tracking(
    video_path: Path,
    model_path: Path,
    store_id: str,
    camera_id: str,
    log_path: Path,
    api_url: str,
    max_frames: Optional[int] = None,
    dwell_interval_frames: int = 45,
    stale_frames: int = 60,
) -> List[dict]:
    cv2, YOLO = _load_runtime_dependencies()
    if cv2 is None or YOLO is None:
        raise RuntimeError("opencv-python and ultralytics are required for real tracking mode")

    if not model_path.exists():
        raise FileNotFoundError(f"Model weights not found: {model_path}")
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    model = YOLO(str(model_path))
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")

    frame_index = 0
    emitted_events: List[dict] = []
    sessions: Dict[int, TrackSession] = {}
    recent_exits: List[RecentExit] = []

    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0

    while cap.isOpened():
        if max_frames is not None and frame_index >= max_frames:
            break

        success, frame = cap.read()
        if not success:
            break

        frame_index += 1
        frame_height, frame_width = frame.shape[:2]
        _ = frame_height
        result = model.track(frame, persist=True, classes=[0], tracker="bytetrack.yaml", verbose=False)[0]
        tracks = _extract_tracks(result)
        visible_track_ids = set()
        queue_depth = _estimate_queue_depth(tracks, frame_width)

        for track_id, coordinates, confidence in tracks:
            visible_track_ids.add(track_id)
            x1, y1, x2, y2 = coordinates
            _ = y1
            _ = y2
            center_x = (x1 + x2) / 2.0
            zone_id = _classify_zone(center_x, frame_width)

            session = sessions.get(track_id)
            reentry_detected = False
            if session is None:
                matched_exit = _match_recent_exit(recent_exits, zone_id, frame_index)
                visitor_id = matched_exit.visitor_id if matched_exit else f"VIS_{track_id:04d}"
                session = TrackSession(
                    visitor_id=visitor_id,
                    first_seen_frame=frame_index,
                    last_seen_frame=frame_index,
                    current_zone=zone_id,
                )
                if matched_exit:
                    session.reentry_count += 1
                    session.entry_emitted = True
                    reentry_detected = True
                sessions[track_id] = session

            zone_changed = zone_id != session.current_zone and session.zone_history
            if reentry_detected:
                event_type = "REENTRY"
            elif session.exit_emitted and frame_index - session.last_seen_frame <= stale_frames:
                session.exit_emitted = False
                event_type = "REENTRY"
            elif not session.entry_emitted:
                event_type = "ENTRY"
            else:
                event_type = None

            session.last_seen_frame = frame_index
            session.last_visible_frame = frame_index
            session.last_center_x = center_x
            session.current_zone = zone_id
            session.zone_history.append(zone_id)

            if zone_changed:
                session.event_seq += 1
                emitted_events.append(
                    build_event_payload(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=session.visitor_id,
                        event_type="ZONE_EXIT",
                        session_seq=session.event_seq,
                        zone_id=session.zone_history[-2],
                        confidence=confidence,
                        source="pipeline.detect.track",
                    )
                )
                session.event_seq += 1
                emitted_events.append(
                    build_event_payload(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=session.visitor_id,
                        event_type="ZONE_ENTER",
                        session_seq=session.event_seq,
                        zone_id=zone_id,
                        confidence=confidence,
                        source="pipeline.detect.track",
                    )
                )

            if event_type:
                session.event_seq += 1
                emitted_events.append(
                    build_event_payload(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=session.visitor_id,
                        event_type=event_type,
                        session_seq=session.event_seq,
                        zone_id=zone_id,
                        confidence=confidence,
                        source="pipeline.detect.track",
                    )
                )
                session.entry_emitted = True

            if zone_id == QUEUE_ZONE and queue_depth > 0:
                session.has_billing_queue = True
                session.event_seq += 1
                emitted_events.append(
                    build_event_payload(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=session.visitor_id,
                        event_type="BILLING_QUEUE_JOIN",
                        session_seq=session.event_seq,
                        zone_id=zone_id,
                        dwell_ms=0,
                        queue_depth=queue_depth,
                        confidence=min(1.0, confidence),
                        source="pipeline.detect.track",
                    )
                )

            dwell_due = frame_index - session.first_seen_frame >= dwell_interval_frames
            if dwell_due and frame_index - session.last_dwell_frame >= dwell_interval_frames:
                session.event_seq += 1
                session.last_dwell_frame = frame_index
                dwell_ms = int(((frame_index - session.first_seen_frame) / fps) * 1000)
                emitted_events.append(
                    build_event_payload(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=session.visitor_id,
                        event_type="ZONE_DWELL",
                        session_seq=session.event_seq,
                        zone_id=zone_id,
                        dwell_ms=dwell_ms,
                        confidence=confidence,
                        source="pipeline.detect.track",
                    )
                )

            distinct_zones = len({zone for zone in session.zone_history if zone})
            long_session = frame_index - session.first_seen_frame >= dwell_interval_frames * 2
            if not session.is_staff and long_session and distinct_zones >= STAFF_ZONE_THRESHOLD:
                session.is_staff = True

        for track_id, session in sessions.items():
            if track_id in visible_track_ids or session.exit_emitted:
                continue
            if frame_index - session.last_seen_frame >= stale_frames:
                session.event_seq += 1
                if session.has_billing_queue:
                    emitted_events.append(
                        build_event_payload(
                            store_id=store_id,
                            camera_id=camera_id,
                            visitor_id=session.visitor_id,
                            event_type="BILLING_QUEUE_ABANDON",
                            session_seq=session.event_seq,
                            zone_id=QUEUE_ZONE,
                            dwell_ms=int(((session.last_seen_frame - session.first_seen_frame) / fps) * 1000),
                            confidence=0.82,
                            source="pipeline.detect.track",
                        )
                    )
                    session.event_seq += 1
                session.exit_emitted = True
                dwell_ms = int(((session.last_seen_frame - session.first_seen_frame) / fps) * 1000)
                emitted_events.append(
                    build_event_payload(
                        store_id=store_id,
                        camera_id=camera_id,
                        visitor_id=session.visitor_id,
                        event_type="EXIT",
                        session_seq=session.event_seq,
                        zone_id="EXIT",
                        dwell_ms=dwell_ms,
                        confidence=1.0,
                        source="pipeline.detect.track",
                    )
                )
                recent_exits.append(
                    RecentExit(
                        visitor_id=session.visitor_id,
                        frame_index=frame_index,
                        zone_id=session.current_zone,
                        center_x=session.last_center_x,
                    )
                )

    for session in sessions.values():
        if session.exit_emitted:
            continue
        session.event_seq += 1
        dwell_ms = int(((session.last_seen_frame - session.first_seen_frame) / fps) * 1000)
        emitted_events.append(
            build_event_payload(
                store_id=store_id,
                camera_id=camera_id,
                visitor_id=session.visitor_id,
                event_type="EXIT",
                session_seq=session.event_seq,
                zone_id="EXIT",
                dwell_ms=dwell_ms,
                confidence=1.0,
                source="pipeline.detect.track",
            )
        )
        recent_exits.append(
            RecentExit(
                visitor_id=session.visitor_id,
                frame_index=frame_index,
                zone_id=session.current_zone,
                center_x=session.last_center_x,
            )
        )

    cap.release()
    write_events(log_path, emitted_events)
    post_events(api_url, emitted_events)
    return emitted_events


def process_video(
    video_path: Optional[Path] = None,
    model_path: Optional[Path] = None,
    store_id: str = "STORE_BLR_002",
    camera_id: str = "CAM_ENTRY_01",
    log_path: Optional[Path] = None,
    api_url: Optional[str] = None,
    dry_run: bool = False,
    max_frames: Optional[int] = None,
) -> List[dict]:
    resolved_video = Path(video_path) if video_path is not None else DEFAULT_VIDEO
    resolved_model = Path(model_path) if model_path is not None else DEFAULT_MODEL
    resolved_log = Path(log_path) if log_path is not None else DEFAULT_LOG
    resolved_api_url = api_url or os.getenv("API_URL", "http://127.0.0.1:8000")

    if dry_run:
        events = _simulate_events(store_id=store_id, camera_id=camera_id)
        write_events(resolved_log, events)
        post_events(resolved_api_url, events)
        return events

    try:
        return _run_real_tracking(
            video_path=resolved_video,
            model_path=resolved_model,
            store_id=store_id,
            camera_id=camera_id,
            log_path=resolved_log,
            api_url=resolved_api_url,
            max_frames=max_frames,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[pipeline] Falling back to dry run: {exc}")
        events = _simulate_events(store_id=store_id, camera_id=camera_id)
        write_events(resolved_log, events)
        post_events(resolved_api_url, events)
        return events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apex Retail detection pipeline")
    parser.add_argument("--video-path", type=Path, default=None)
    parser.add_argument("--model-path", type=Path, default=None)
    parser.add_argument("--log-path", type=Path, default=None)
    parser.add_argument("--api-url", type=str, default=None)
    parser.add_argument("--store-id", type=str, default="STORE_BLR_002")
    parser.add_argument("--camera-id", type=str, default="CAM_ENTRY_01")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-frames", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    events = process_video(
        video_path=args.video_path,
        model_path=args.model_path,
        log_path=args.log_path,
        api_url=args.api_url,
        store_id=args.store_id,
        camera_id=args.camera_id,
        dry_run=args.dry_run,
        max_frames=args.max_frames,
    )
    print(json.dumps({"emitted_events": len(events), "log_path": str(args.log_path or DEFAULT_LOG)}, indent=2))


if __name__ == "__main__":
    main()