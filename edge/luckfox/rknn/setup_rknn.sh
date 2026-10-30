#!/usr/bin/env bash
# One-time setup of the RKNN conversion environment on an Ubuntu 22.04 or 24.04 x86_64 VPS.
# CPU only, no GPU needed. Needs sudo for apt.   Usage:  bash setup_rknn.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. /etc/os-release
case "${VERSION_ID}" in
  22.04) PYV=3.10; GLIB=libglib2.0-0;    CONS="$HERE/constraints-ubuntu2204.txt" ;;
  24.04) PYV=3.12; GLIB=libglib2.0-0t64; CONS="$HERE/constraints-ubuntu2404.txt" ;;
  *) echo "Hanya Ubuntu 22.04 atau 24.04 (terdeteksi: ${PRETTY_NAME})"; exit 1 ;;
esac
[ "$(uname -m)" = "x86_64" ] || { echo "Butuh VPS x86_64 (terdeteksi $(uname -m))"; exit 1; }
[ -f "$CONS" ] || { echo "File $CONS tidak ada: upload juga constraints-ubuntu*.txt"; exit 1; }
SUDO=sudo; [ "$(id -u)" -eq 0 ] && SUDO=          # root on minimal images often has no sudo
echo "== ${PRETTY_NAME}, Python ${PYV}, RAM $(free -m | awk '/Mem:/{print $2}') MB"

$SUDO apt-get update
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  "python${PYV}-venv" python3-venv python3-pip libgl1 "$GLIB" libgomp1 \
  zip unzip git ca-certificates curl

# Ubuntu 24.04 (PEP 668) refuses system-wide pip: everything goes into a venv.
"python${PYV}" -m venv "$HOME/rknn-venv"
. "$HOME/rknn-venv/bin/activate"
python -m pip install --upgrade "pip<26" wheel
cp "$CONS" "$HOME/rknn-constraints.txt"
# Ultralytics may auto-install packages during export, with uv when present: guard both.
export PIP_CONSTRAINT="$HOME/rknn-constraints.txt" UV_CONSTRAINT="$HOME/rknn-constraints.txt"

# 1) CPU-only torch first (PyPI torch pulls several GB of CUDA libraries)
pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.4.0+cpu torchvision==0.19.0+cpu
# 2) everything else exactly as pinned (numpy is never upgraded past 1.26.4)
grep -v -E '^(#|torch|torchvision)' "$CONS" | xargs pip install --no-cache-dir

pip check
python - <<'PY'
import numpy, onnx, onnxruntime, torch, ultralytics
from rknn.api import RKNN
assert numpy.__version__ == "1.26.4", numpy.__version__
print("OK  rknn-toolkit2 siap | ultralytics", ultralytics.__version__, "| torch", torch.__version__,
      "| onnx", onnx.__version__, "| onnxruntime", onnxruntime.__version__, "| numpy", numpy.__version__)
PY
echo "Selesai. Berikutnya: bash export_rknn.sh ppe_project.pt rknn_calib.zip 320"
