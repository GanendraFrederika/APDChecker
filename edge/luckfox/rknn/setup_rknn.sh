#!/usr/bin/env bash
# One-time setup of the RKNN conversion environment on a Linux server (x86_64 or
# aarch64, Python 3.10/3.11, >= 4 GB RAM, >= 10 GB disk). No root needed.
#   bash setup_rknn.sh
set -euo pipefail
PY=${PYTHON:-python3}
echo "== Sistem"; uname -m; $PY --version
case "$($PY -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')" in
  3.10|3.11) ;;
  *) echo "Butuh Python 3.10 atau 3.11 (rknn-toolkit2 2.3.2). Pilih versi itu di egg."; exit 1;;
esac
$PY -m venv "$HOME/rknn-env" 2>/dev/null || { $PY -m pip install --user virtualenv && $PY -m virtualenv "$HOME/rknn-env"; }
. "$HOME/rknn-env/bin/activate"
pip install --upgrade pip
# CPU-only torch keeps the download small; rknn-toolkit2 2.3.2 needs torch <= 2.4 and numpy <= 1.26.4
pip install "torch==2.4.0" "torchvision==0.19.0" --index-url https://download.pytorch.org/whl/cpu
pip install "ultralytics==8.4.175" "rknn-toolkit2==2.3.2" "onnx>=1.16.1,<1.19" "numpy<=1.26.4" \
            "setuptools<82" onnxruntime
python - <<'PY'
from rknn.api import RKNN
import ultralytics, torch, numpy
print("OK  rknn-toolkit2 siap | ultralytics", ultralytics.__version__, "| torch", torch.__version__, "| numpy", numpy.__version__)
PY
echo "Selesai. Berikutnya: bash export_rknn.sh ppe_project.pt rknn_calib.zip"
