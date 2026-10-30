#!/usr/bin/env bash
# Convert a trained YOLO model to an INT8 .rknn for the Luckfox Pico (RV1103/RV1106).
#   bash export_rknn.sh MODEL.pt rknn_calib.zip [imgsz=320] [chip=rv1103]
# rknn_calib.zip comes from scripts/make_rknn_calib.py on the Windows PC: 100-300 photos
# that look like the real camera (INT8 learns its value ranges from them).
set -euo pipefail
MODEL=${1:?model .pt}; CALIB=${2:?rknn_calib.zip}; IMGSZ=${3:-320}; CHIP=${4:-rv1103}
. "$HOME/rknn-venv/bin/activate"
export PIP_CONSTRAINT="$HOME/rknn-constraints.txt" UV_CONSTRAINT="$HOME/rknn-constraints.txt"
export ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS=1             # everything is pre-installed: no auto-install
export YOLO_OFFLINE=1
rm -rf calib && mkdir calib && unzip -q "$CALIB" -d calib
test -f calib/data.yaml || { echo "calib/data.yaml tidak ada di dalam zip"; exit 1; }
yolo export model="$MODEL" format=rknn name="$CHIP" imgsz="$IMGSZ" quantize=8 batch=1 data=calib/data.yaml
OUT="${MODEL%.*}_rknn_model"                 # ultralytics writes it next to the .pt
NAME="$(basename "$OUT")"
pip check
ls -la "$OUT"
( cd "$OUT" && sha256sum ./*.rknn | tee SHA256SUMS )
( cd "$(dirname "$OUT")" && zip -qr "$PWD/${NAME}.zip" "$NAME" )
echo "Selesai: $(cd "$(dirname "$OUT")" && pwd)/${NAME}.zip"
