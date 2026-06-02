from pathlib import Path
import zipfile
import os

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "submission.zip"

EXCLUDE_FILES = {"yolov8n.pt"}
EXCLUDE_DIRS = {"footage"}

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT)
        # skip excluded directories
        parts = rel_dir.split(os.sep)
        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        for fname in filenames:
            if fname in EXCLUDE_FILES:
                continue
            fp = Path(dirpath) / fname
            arcname = os.path.relpath(fp, ROOT)
            z.write(fp, arcname)

print(f"Created {OUT}")
