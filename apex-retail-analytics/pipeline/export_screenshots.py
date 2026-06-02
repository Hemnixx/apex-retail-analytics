from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List, Tuple


def parse_args():
    parser = argparse.ArgumentParser(description="Export top-N screenshot frames using YOLO detections")
    parser.add_argument("--video-path", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=Path(__file__).resolve().parent.parent / "yolov8n.pt")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "artifacts" / "screenshots")
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--max-frames", type=int, default=1000)
    parser.add_argument("--min-conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    return parser.parse_args()


def annotate_frame(img, boxes_xyxy, confs, ids=None):
    try:
        import cv2
    except Exception:
        raise
    out = img.copy()
    for idx, ((x1, y1, x2, y2), c) in enumerate(zip(boxes_xyxy, confs)):
        x1i, y1i, x2i, y2i = int(x1), int(y1), int(x2), int(y2)
        cv2.rectangle(out, (x1i, y1i), (x2i, y2i), (0, 255, 0), 2)
        track_id = None
        if ids is not None and idx < len(ids) and ids[idx] is not None:
            try:
                track_id = int(ids[idx])
            except Exception:
                track_id = ids[idx]
        if track_id is not None:
            label = f"ID:{track_id} {c:.2f}"
        else:
            label = f"person {c:.2f}"
        t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        cv2.rectangle(out, (x1i, y1i - t_size[1] - 6), (x1i + t_size[0] + 6, y1i), (0, 255, 0), -1)
        cv2.putText(out, label, (x1i + 3, y1i - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return out


def main():
    args = parse_args()

    try:
        import cv2
        from ultralytics import YOLO
        import numpy as np
    except Exception:
        print("Missing dependencies: install opencv-python and ultralytics")
        raise

    if not args.video_path.exists():
        print(f"Video not found: {args.video_path}")
        sys.exit(2)
    if not args.model_path.exists():
        print(f"Model not found: {args.model_path}")
        sys.exit(2)

    model = YOLO(str(args.model_path))
    cap = cv2.VideoCapture(str(args.video_path))
    if not cap.isOpened():
        print(f"Unable to open video: {args.video_path}")
        sys.exit(2)

    frames_info: List[Tuple[int, int, float, List[List[float]], List[float], List[int]]] = []
    frame_idx = 0
    max_frames = args.max_frames
    # Use YOLO track() to get stable track IDs per detection
    frame_idx = 0
    for res in model.track(str(args.video_path), imgsz=args.imgsz, conf=args.min_conf, classes=[0], stream=True):
        frame_idx += 1
        if frame_idx > max_frames:
            break
        boxes = getattr(res, "boxes", None)
        if boxes is None or len(boxes) == 0:
            continue
        xyxy = boxes.xyxy.cpu().numpy().tolist()
        confs = boxes.conf.cpu().numpy().tolist() if getattr(boxes, "conf", None) is not None else [1.0] * len(xyxy)
        ids = boxes.id.cpu().numpy().tolist() if getattr(boxes, "id", None) is not None else [None] * len(xyxy)
        person_count = len(xyxy)
        avg_conf = float(sum(confs) / len(confs)) if confs else 0.0
        frames_info.append((frame_idx, person_count, avg_conf, xyxy, confs, ids))

    cap.release()

    if not frames_info:
        print("No person detections found in scanned frames.")
        return

    # Rank frames by person_count desc, avg_conf desc
    frames_info.sort(key=lambda x: (x[1], x[2]), reverse=True)
    chosen = frames_info[: args.top_n]

    args.output.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.video_path))
    saved = 0
    wanted = {idx for idx, *_ in chosen}
    frame_idx = 0
    while True and wanted:
        success, img = cap.read()
        if not success:
            break
        frame_idx += 1
        if frame_idx in wanted:
            info = next(item for item in chosen if item[0] == frame_idx)
            _, count, avg_conf, xyxy, confs, ids = info
            annotated = annotate_frame(img, xyxy, confs, ids=ids)
            out_path = args.output / f"frame_{frame_idx:06d}_count{count}_conf{avg_conf:.2f}.png"
            cv2.imwrite(str(out_path), annotated)
            print(f"Wrote: {out_path}")
            wanted.remove(frame_idx)
            saved += 1

    cap.release()
    print(f"Saved {saved} screenshot(s) to: {args.output}")


if __name__ == "__main__":
    main()
