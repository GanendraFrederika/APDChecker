#!/usr/bin/env bash
# Convert a trained YOLO model to an INT8 .rknn for the Luckfox Pico Mini B (RV1103).
#   bash export_rknn.sh ppe_project.pt rknn_calib.zip [imgsz=320]
# rknn_calib.zip comes from scripts/make_rknn_calib.py on the Windows PC (100-300 photos
# that look like the real camera: INT8 quantization learns its value ranges from them).
set -euo pipefail
MODEL=${1:?model .pt}; CALIB=${2:?rknn_calib.zip}; IMGSZ=${3:-320}
. "$HOME/rknn-env/bin/activate"
rm -rf calib && mkdir calib && python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall('calib')" "$CALIB"
test -f calib/data.yaml || { echo "calib/data.yaml tidak ada di zip"; exit 1; }
export YOLO_OFFLINE=1
yolo export model="$MODEL" format=rknn name=rv1103 imgsz="$IMGSZ" quantize=8 batch=1 data=calib/data.yaml
OUT="$(basename "${MODEL%.*}")_rknn_model"
ls -la "$OUT"
( cd "$OUT" && sha256sum ./*.rknn )
zip -qr "${OUT}.zip" "$OUT" 2>/dev/null || python -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', '.', sys.argv[1])" "$OUT"
echo "Selesai: unduh ${OUT}.zip lewat file manager panel."
