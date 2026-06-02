from __future__ import annotations

import argparse
from pathlib import Path
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Live view YOLO detections on video")
    p.add_argument("--video-path", type=Path, required=True)
    p.add_argument("--model-path", type=Path, default=Path(__file__).resolve().parent.parent / "yolov8n.pt")
    p.add_argument("--use-track", action="store_true", help="Use model.track to get stable IDs")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--wait-ms", type=int, default=1, help="cv2 waitKey delay in ms")
    return p.parse_args()


def draw_boxes(frame, xyxy_list, confs, ids=None):
    import cv2

    for i, box in enumerate(xyxy_list):
        x1, y1, x2, y2 = map(int, box)
        c = confs[i] if i < len(confs) else 1.0
        id_label = f" ID:{ids[i]}" if ids is not None and i < len(ids) else ""
        color = (0, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"person {c:.2f}{id_label}"
        t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        cv2.rectangle(frame, (x1, y1 - t_size[1] - 6), (x1 + t_size[0] + 6, y1), color, -1)
        cv2.putText(frame, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)


def main():
    args = parse_args()

    try:
        import cv2
        from ultralytics import YOLO
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

    window_name = "YOLO Live View - press Q to quit"
    headless = False
    try:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    except Exception:
        print("OpenCV build has no GUI support; falling back to saving annotated video.")
        headless = True

    writer = None
    out_path = None

    while True:
        success, frame = cap.read()
        if not success:
            break

        try:
            if args.use_track:
                result = model.track(frame, persist=True, classes=[0], tracker="bytetrack.yaml", verbose=False)[0]
            else:
                result = model.predict(frame, imgsz=args.imgsz, conf=args.conf, classes=[0])[0]
        except Exception as exc:
            print(f"Model inference failed: {exc}")
            break

        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            annotated = frame
        else:
            xyxy = boxes.xyxy.cpu().numpy().tolist()
            confs = boxes.conf.cpu().numpy().tolist() if getattr(boxes, "conf", None) is not None else [1.0] * len(xyxy)
            ids = None
            if args.use_track and getattr(boxes, "id", None) is not None:
                try:
                    ids = boxes.id.cpu().numpy().astype(int).tolist()
                except Exception:
                    ids = None
            annotated = frame.copy()
            draw_boxes(annotated, xyxy, confs, ids)

        if headless:
            if writer is None:
                fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                h, w = annotated.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                out_path = args.video_path.parent / ".." / "apex-retail-analytics" / "artifacts" / "detection_live_output.mp4"
                out_path = out_path.resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                writer = cv2.VideoWriter(str(out_path), fourcc, float(fps), (w, h))
            writer.write(annotated)
        else:
            cv2.imshow(window_name, annotated)
            key = cv2.waitKey(args.wait_ms) & 0xFF
            if key == ord("q"):
                break

    cap.release()
    if writer is not None:
        writer.release()
        try:
            import os
            if sys.platform.startswith("win"):
                os.startfile(str(out_path))
            else:
                print(f"Wrote annotated video to: {out_path}")
        except Exception:
            print(f"Wrote annotated video to: {out_path}")
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass


if __name__ == "__main__":
    main()
