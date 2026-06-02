from __future__ import annotations

import argparse
from pathlib import Path
import sys


def parse_args():
    parser = argparse.ArgumentParser(description="Run YOLO on a single video frame and save annotated image")
    parser.add_argument("--video-path", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, default=Path(__file__).resolve().parent.parent / "yolov8n.pt")
    parser.add_argument("--frame-index", type=int, default=120)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent.parent / "artifacts" / "detection_yolo.png")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        import cv2  # type: ignore
        from ultralytics import YOLO  # type: ignore
        import numpy as np
    except Exception as exc:
        print("Missing dependencies: please install opencv-python and ultralytics")
        raise

    if not args.video_path.exists():
        print(f"Video not found: {args.video_path}")
        sys.exit(2)
    if not args.model_path.exists():
        print(f"Model not found: {args.model_path}")
        sys.exit(2)

    cap = cv2.VideoCapture(str(args.video_path))
    if not cap.isOpened():
        print(f"Unable to open video: {args.video_path}")
        sys.exit(2)

    # Seek to requested frame (1-based in detect.py, use same convention)
    target = args.frame_index
    frame_idx = 0
    frame = None
    while True:
        success, img = cap.read()
        if not success:
            break
        frame_idx += 1
        if frame_idx == target:
            frame = img
            break

    cap.release()
    if frame is None:
        print(f"Could not read frame {target} from video (only read {frame_idx} frames)")
        sys.exit(2)

    model = YOLO(str(args.model_path))
    # Run a single-frame detection (no tracker) for reliable person boxes
    results = model.predict(frame, imgsz=640, conf=0.25, classes=[0])
    res = results[0]

    boxes = getattr(res, "boxes", None)
    annotated = frame.copy()
    h, w = annotated.shape[:2]
    if boxes is None or len(boxes) == 0:
        print("No person detections on that frame")
    else:
        xyxy = boxes.xyxy.cpu().numpy()
        conf = boxes.conf.cpu().numpy() if getattr(boxes, "conf", None) is not None else [1.0] * len(xyxy)
        cls = boxes.cls.cpu().numpy() if getattr(boxes, "cls", None) is not None else [0] * len(xyxy)
        for (x1, y1, x2, y2), c, cl in zip(xyxy, conf, cls):
            x1i, y1i, x2i, y2i = int(x1), int(y1), int(x2), int(y2)
            cv2.rectangle(annotated, (x1i, y1i), (x2i, y2i), (0, 255, 0), 2)
            label = f"person {c:.2f}"
            t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.rectangle(annotated, (x1i, y1i - t_size[1] - 6), (x1i + t_size[0] + 6, y1i), (0, 255, 0), -1)
            cv2.putText(annotated, label, (x1i + 3, y1i - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), annotated)
    print(f"Wrote YOLO-annotated frame to: {args.output}")


if __name__ == "__main__":
    main()
