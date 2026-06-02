from __future__ import annotations

import argparse
from pathlib import Path
import json
from typing import List, Tuple

def parse_args():
    p = argparse.ArgumentParser(description="Evaluate detections against simple CSV ground truth")
    p.add_argument("--detections", type=Path, default=Path(__file__).resolve().parent.parent / "artifacts" / "detection_events.jsonl")
    p.add_argument("--ground-truth", type=Path, required=True, help="CSV file: frame_idx,x1,y1,x2,y2")
    p.add_argument("--iou", type=float, default=0.5)
    return p.parse_args()


def iou(boxA, boxB):
    # boxes: [x1,y1,x2,y2]
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interW = max(0, xB - xA)
    interH = max(0, yB - yA)
    interArea = interW * interH
    if interArea == 0:
        return 0.0
    boxAArea = max(0, boxA[2] - boxA[0]) * max(0, boxA[3] - boxA[1])
    boxBArea = max(0, boxB[2] - boxB[0]) * max(0, boxB[3] - boxB[1])
    return interArea / float(boxAArea + boxBArea - interArea)


def load_ground_truth(path: Path):
    gt = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            frame = int(parts[0])
            box = [float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])]
            gt.setdefault(frame, []).append(box)
    return gt


def load_detections(path: Path):
    # Expecting detection_events.jsonl with entries containing frame and bbox
    det = {}
    if not path.exists():
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            frame = obj.get("frame") or obj.get("frame_idx") or obj.get("frame_index")
            bbox = obj.get("bbox") or obj.get("box")
            if frame is None or bbox is None:
                # try nested structure used by detect.py (tracks)
                frame = obj.get("frame_idx")
                bbox = obj.get("xyxy")
            if frame is None or bbox is None:
                continue
            # normalize bbox to [x1,y1,x2,y2]
            if isinstance(bbox, list) and len(bbox) >= 4:
                box = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                det.setdefault(int(frame), []).append(box)
    return det


def evaluate(dets, gts, iou_thresh=0.5):
    TP = 0
    FP = 0
    FN = 0
    frames = sorted(set(list(dets.keys()) + list(gts.keys())))
    per_frame = {}
    for f in frames:
        D = dets.get(f, [])[:]
        G = gts.get(f, [])[:]
        matched = set()
        for i, g in enumerate(G):
            best_j = -1
            best_iou = 0.0
            for j, d in enumerate(D):
                if j in matched:
                    continue
                val = iou(g, d)
                if val > best_iou:
                    best_iou = val
                    best_j = j
            if best_j >= 0 and best_iou >= iou_thresh:
                TP += 1
                matched.add(best_j)
            else:
                FN += 1
        FP += len(D) - len(matched)
        per_frame[f] = {"tp": len(matched), "fp": len(D) - len(matched), "fn": len(G) - len(matched)}
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0.0
    recall = TP / (TP + FN) if (TP + FN) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"TP": TP, "FP": FP, "FN": FN, "precision": precision, "recall": recall, "f1": f1, "per_frame": per_frame}


def main():
    args = parse_args()
    gts = load_ground_truth(args.ground_truth)
    dets = load_detections(args.detections)
    stats = evaluate(dets, gts, iou_thresh=args.iou)
    print("Evaluation result:")
    print(json.dumps({k: stats[k] for k in ["TP", "FP", "FN", "precision", "recall", "f1"]}, indent=2))


if __name__ == "__main__":
    main()
