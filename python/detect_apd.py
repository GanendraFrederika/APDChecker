"""Webcam/RTSP PPE detection and optional supervised PPE1/v2.2 sender.
Example: python detect_apd.py --camera 0 --no-web --show
Never use a generic person detector to claim APD LENGKAP.
"""
from apd_runtime.live_camera import main

if __name__ == "__main__":
    raise SystemExit(main())
