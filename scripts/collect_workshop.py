"""Collect training photos from the running Sentinel dashboard, pre-labelled by the AI.

While the app runs (http://127.0.0.1:8080), this saves the RAW upright camera frame
whenever a person is in view (max one per --every seconds) plus a YOLO label file
that the current models produce. Then you only CORRECT labels instead of drawing
every box: open the folder in a free labeller (e.g. https://www.makesense.ai or
Label Studio), fix wrong/missing boxes, export YOLO, and run scripts/train_ppe.py.

Classes (the project's own set): 0 helmet, 1 vest, 2 shoes, 3 person.
Record variety: with and without each item, different people, distance, light, angle.

  .venv\\Scripts\\python.exe scripts\\collect_workshop.py --minutes 15
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
CLASSES = ("helmet", "vest", "shoes", "person")


def grab_jpeg(url="http://127.0.0.1:8080/raw.jpg"):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "datasets/workshop"))
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--every", type=float, default=2.0, help="seconds between saved frames")
    ap.add_argument("--all", action="store_true", help="also save frames without people (background)")
    args = ap.parse_args()
    import cv2
    import numpy as np
    from sentinel.vision import Perception
    os.environ.setdefault("YOLO_OFFLINE", "1")
    per = Perception()
    out_img, out_lbl = Path(args.out) / "images", Path(args.out) / "labels"
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    t_end, last, saved = time.time() + 60 * args.minutes, 0.0, 0
    print(f"Merekam ke {args.out} selama {args.minutes:.0f} menit. Ctrl+C untuk berhenti.")
    while time.time() < t_end:
        try:
            data = grab_jpeg()
        except OSError as exc:
            print("dashboard tidak menjawab:", exc)
            time.sleep(2)
            continue
        if time.time() - last < args.every:
            time.sleep(0.2)
            continue
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        people = per.people(frame)
        if not people and not args.all:
            time.sleep(0.3)
            continue
        per._boots_at = -1e9
        ppe = per.equipment(frame, people)
        h, w = frame.shape[:2]
        rows = []
        for p in people:
            rows.append((3, p.box))
        for d in ppe:
            if d.label in ("helmet", "vest", "shoes"):
                rows.append((CLASSES.index(d.label), d.box))
        name = time.strftime("ws_%Y%m%d_%H%M%S")
        cv2.imwrite(str(out_img / f"{name}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        with open(out_lbl / f"{name}.txt", "w", encoding="utf-8") as f:
            for c, (x1, y1, x2, y2) in rows:
                f.write(f"{c} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}\n")
        saved += 1
        last = time.time()
        print(f"{saved:4d} {name}: {len(people)} orang, " +
              ", ".join(f"{CLASSES[c]}" for c, _ in rows if c != 3))
    meta = dict(saved=saved, models=per.models, note="labels are AI suggestions: review before training")
    (Path(args.out) / "collect_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"Selesai: {saved} foto. Periksa/perbaiki label, lalu jalankan scripts/train_ppe.py.")


if __name__ == "__main__":
    main()
