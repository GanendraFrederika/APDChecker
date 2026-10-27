"""Compare PPE detectors on one labelled set, mapped to the classes this project needs.

Every model names its classes differently ("Hard_hat", "Hardhat", "helmet"...). Each is
mapped to: helmet, no_helmet, vest, no_vest, shoes, no_shoes, person. Metrics per class:
AP50 (area under the precision/recall curve at IoU 0.5), and precision/recall at the
confidence the runtime uses. Plus CPU time per image on THIS PC.

  .venv\\Scripts\\python.exe scripts\\eval_ppe.py --data datasets/construction-ppe --split val
"""
import argparse
import json
import os
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CANON = ("helmet", "no_helmet", "vest", "no_vest", "shoes", "no_shoes", "person")

# label names (lower-case, '-' and ' ' -> '_') -> canonical
ALIASES = {
    "helmet": "helmet", "hardhat": "helmet", "hard_hat": "helmet", "hard-hat": "helmet",
    "no_helmet": "no_helmet", "no_hardhat": "no_helmet", "nohelmet": "no_helmet",
    "vest": "vest", "safety_vest": "vest", "reflective_vest": "vest",
    "no_vest": "no_vest", "no_safety_vest": "no_vest",
    "shoes": "shoes", "boots": "shoes", "safety_shoes": "shoes",
    "no_shoes": "no_shoes", "no_boots": "no_shoes",
    "person": "person", "worker": "person", "human": "person",
}


def canon(name):
    return ALIASES.get(name.lower().strip().replace("-", "_").replace(" ", "_"))


def load_truth(data, split):
    import yaml
    cfg = yaml.safe_load(open(data / "data.yaml", encoding="utf-8")) if (data / "data.yaml").exists() else None
    names = cfg["names"] if cfg else None
    if names is None:
        raise SystemExit("data.yaml with names required")
    if isinstance(names, list):
        names = dict(enumerate(names))
    imgs = sorted(p for p in (data / "images" / split).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    truth = {}
    for p in imgs:
        lab = data / "labels" / split / (p.stem + ".txt")
        rows = []
        if lab.exists():
            for line in lab.read_text().split("\n"):
                parts = line.split()
                if len(parts) >= 5:
                    c = canon(names[int(parts[0])])
                    if c:
                        rows.append((c, *map(float, parts[1:5])))
        truth[p] = rows
    return truth


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def ap50(dets, n_true):
    """dets: list of (conf, is_tp). VOC-style all-point AP."""
    if n_true == 0:
        return None
    dets = sorted(dets, key=lambda d: -d[0])
    tp = np.cumsum([d[1] for d in dets]) if dets else np.array([0])
    fp = np.cumsum([1 - d[1] for d in dets]) if dets else np.array([0])
    rec = tp / n_true
    prec = tp / np.maximum(tp + fp, 1e-9)
    mrec = np.concatenate([[0], rec, [1]])
    mpre = np.concatenate([[1], prec, [0]])
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def evaluate(model_path, truth, imgsz, conf_report):
    os.environ.setdefault("YOLO_OFFLINE", "1")
    from ultralytics import YOLO
    model = YOLO(str(model_path))
    names = {i: canon(n) for i, n in model.names.items()}
    covered = sorted({c for c in names.values() if c})
    per = {c: dict(dets=[], n=0) for c in CANON}
    times = []
    for k, (path, rows) in enumerate(truth.items()):
        t0 = time.perf_counter()
        r = model.predict(str(path), imgsz=imgsz, conf=0.05, device="cpu", verbose=False, max_det=100)[0]
        if k >= 2:
            times.append(time.perf_counter() - t0)
        h, w = r.orig_shape
        gts = {}
        for c, cx, cy, bw, bh in rows:
            gts.setdefault(c, []).append([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h, False])
        for c in CANON:
            per[c]["n"] += len(gts.get(c, []))
        preds = []
        for b, cf, cl in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy()):
            c = names.get(int(cl))
            if c:
                preds.append((float(cf), c, b.tolist()))
        for cf, c, b in sorted(preds, key=lambda p: -p[0]):
            best, bi = 0.0, None
            for i, g in enumerate(gts.get(c, [])):
                if not g[4]:
                    v = iou(b, g)
                    if v > best:
                        best, bi = v, i
            tp = best >= 0.5
            if tp:
                gts[c][bi][4] = True
            per[c]["dets"].append((cf, int(tp)))
    out = {}
    for c in CANON:
        if c not in covered:
            continue
        d, n = per[c]["dets"], per[c]["n"]
        hit = [x for x in d if x[0] >= conf_report]
        tp = sum(x[1] for x in hit)
        out[c] = dict(n=n, ap50=None if n == 0 else round(ap50(d, n), 3),
                      precision=round(tp / len(hit), 3) if hit else None,
                      recall=round(tp / n, 3) if n else None)
    return dict(model=model_path.name, covered=covered, ms=round(1000 * float(np.median(times)), 1), per_class=out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "datasets/construction-ppe"))
    ap.add_argument("--split", default="val")
    ap.add_argument("--imgsz", type=int, default=416)
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("models", nargs="*")
    args = ap.parse_args()
    truth = load_truth(Path(args.data), args.split)
    if args.limit:
        truth = dict(list(truth.items())[:args.limit])
    models = [Path(m) for m in args.models] or [ROOT / "models/ppe_yolov8n.pt", *sorted((ROOT / "models/candidates").glob("*.pt"))]
    results = []
    for m in models:
        res = evaluate(m, truth, args.imgsz, args.conf)
        results.append(res)
        print(f"\n{res['model']}  ({res['ms']} ms/gambar @ {args.imgsz}px, {len(truth)} gambar)")
        for c, v in res["per_class"].items():
            print(f"  {c:10s} n={v['n']:4d}  AP50={v['ap50']}  P={v['precision']}  R={v['recall']}")
    out = ROOT / "docs/sentinel/ppe_model_eval.json"
    out.write_text(json.dumps(dict(data=args.data, split=args.split, imgsz=args.imgsz, conf=args.conf,
                                   images=len(truth), results=results), indent=1), encoding="utf-8")
    print("\nsaved", out)


if __name__ == "__main__":
    main()
