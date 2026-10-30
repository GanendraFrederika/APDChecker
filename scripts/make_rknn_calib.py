r"""Build rknn_calib.zip: calibration photos for INT8 conversion of the PPE model.

INT8 quantization measures the value range of every layer on these photos, so they
must look like the real camera: workshop photos first (datasets/workshop), topped up
with construction-ppe validation photos. Upload the zip to the Linux server together
with the .pt and run edge/luckfox/rknn/export_rknn.sh.

  .venv\Scripts\python.exe scripts\make_rknn_calib.py [--count 200]
"""
import argparse
from pathlib import Path
import random
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ("helmet", "vest", "shoes", "person")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--out", default=str(ROOT / "datasets/rknn_calib.zip"))
    args = ap.parse_args()
    ws = sorted((ROOT / "datasets/workshop/images").glob("*.jpg"))
    cp = sorted((ROOT / "datasets/ppe-project/images/val").glob("*.*"))
    random.Random(0).shuffle(ws)
    random.Random(1).shuffle(cp)
    pick = ws[:args.count] + cp[:max(0, args.count - len(ws))]
    if not pick:
        raise SystemExit("Tidak ada foto. Jalankan dulu: scripts\train_ppe.py --prepare-only")
    yaml = ("train: images/val\nval: images/val\nnames:\n" +
            "".join(f"  {i}: {c}\n" for i, c in enumerate(CLASSES)))
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.yaml", yaml)
        for img in pick:
            z.write(img, f"images/val/{img.name}")
            lab = img.parent.parent.parent / "labels" / img.parent.name / (img.stem + ".txt")
            if not lab.exists():
                lab = img.parent.parent / "labels" / (img.stem + ".txt")
            z.writestr(f"labels/val/{img.stem}.txt", lab.read_text() if lab.exists() else "")
    print(f"{args.out}: {len(pick)} foto ({min(len(ws), args.count)} bengkel, "
          f"{len(pick) - min(len(ws), args.count)} construction-ppe)")


if __name__ == "__main__":
    main()
