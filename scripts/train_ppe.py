"""Fine-tune ONE small PPE model for this project: helmet, vest, shoes, person.

Merges (1) the Ultralytics construction-ppe dataset (relabelled to our 4 classes) and
(2) your reviewed workshop photos (datasets/workshop, weighted x3 because they look
like the real deployment), then fine-tunes YOLOv8n starting from the helmet/vest
model. Result: one fast model instead of two -> also the model to convert for the
Pico NPU later (RKNN, 640 or 320 input).

  CPU (this laptop, slow, run overnight):
    .venv\\Scripts\\python.exe scripts\\train_ppe.py --epochs 30 --imgsz 320
  Google Colab / any NVIDIA GPU (~20-30 min):
    python scripts/train_ppe.py --epochs 80 --imgsz 640 --device 0

Afterwards: scripts/eval_ppe.py runs/ppe/<name>/weights/best.pt, and only if it beats
the current models copy it to models/ppe_project.pt (vision.py picks it up first).
"""
import argparse
import os
from pathlib import Path
import random
import shutil

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ("helmet", "vest", "shoes", "person")
CPPE = {0: 0, 2: 1, 3: 2, 6: 3}          # construction-ppe: helmet, vest, boots, Person
# (gloves, goggles, "none" and every no_* class are dropped: "absent" is decided by the
#  tracker from a clearly visible body region WITHOUT the item, not by a weak no_* box)


def convert_cppe(src, dst):
    n = 0
    for split in ("train", "val", "test"):
        (dst / "images" / split).mkdir(parents=True, exist_ok=True)
        (dst / "labels" / split).mkdir(parents=True, exist_ok=True)
        for img in (src / "images" / split).iterdir():
            lab = src / "labels" / split / (img.stem + ".txt")
            rows = []
            if lab.exists():
                for line in lab.read_text().splitlines():
                    p = line.split()
                    if len(p) >= 5 and int(p[0]) in CPPE:
                        rows.append(" ".join([str(CPPE[int(p[0])])] + p[1:5]))
            shutil.copy2(img, dst / "images" / split / img.name)
            (dst / "labels" / split / (img.stem + ".txt")).write_text("\n".join(rows) + ("\n" if rows else ""))
            n += 1
    return n


def add_workshop(src, dst, repeat=3, val_share=0.15, seed=0):
    imgs = sorted((src / "images").glob("*.jpg")) if (src / "images").exists() else []
    if not imgs:
        return 0
    random.Random(seed).shuffle(imgs)
    n_val = max(1, int(len(imgs) * val_share))
    for k, img in enumerate(imgs):
        lab = src / "labels" / (img.stem + ".txt")
        if not lab.exists():
            continue
        split = "val" if k < n_val else "train"
        copies = 1 if split == "val" else repeat
        for r in range(copies):
            name = f"{img.stem}_r{r}"
            shutil.copy2(img, dst / "images" / split / f"{name}.jpg")
            shutil.copy2(lab, dst / "labels" / split / f"{name}.txt")
    return len(imgs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--base", default=str(ROOT / "models/ppe_helmet_vest.pt"))
    ap.add_argument("--name", default="project")
    ap.add_argument("--prepare-only", action="store_true")
    args = ap.parse_args()
    data = ROOT / "datasets/ppe-project"
    if data.exists():
        shutil.rmtree(data)
    n1 = convert_cppe(ROOT / "datasets/construction-ppe", data)
    n2 = add_workshop(ROOT / "datasets/workshop", data)
    (data / "data.yaml").write_text(
        f"path: {data.as_posix()}\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n" + "".join(f"  {i}: {c}\n" for i, c in enumerate(CLASSES)), encoding="utf-8")
    print(f"dataset: {n1} construction-ppe + {n2} workshop photos -> {data}")
    if args.prepare_only:
        return
    os.environ.setdefault("YOLO_OFFLINE", "1")
    from ultralytics import YOLO
    model = YOLO(args.base)
    model.train(data=str(data / "data.yaml"), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device, workers=0 if args.device == "cpu" else 4, project=str(ROOT / "runs/ppe"),
                name=args.name, exist_ok=True, patience=15, cos_lr=True, close_mosaic=5,
                hsv_v=0.5, degrees=10, fliplr=0.5, plots=False)
    best = ROOT / "runs/ppe" / args.name / "weights/best.pt"
    print("best weights:", best)
    print("evaluate: .venv\\Scripts\\python.exe scripts\\eval_ppe.py --data datasets/ppe-project --split test", best)


if __name__ == "__main__":
    main()
