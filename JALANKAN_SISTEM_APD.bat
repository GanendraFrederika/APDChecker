@echo off
setlocal
cd /d "%~dp0"
title APD CAMERA - SERIAL OFF
echo Kamera dan dashboard saja. Arduino TIDAK dikendalikan.
echo Dashboard: http://127.0.0.1:5000 - buka setelah server siap.
echo Tekan Ctrl+C untuk berhenti. Batas default 5 menit.
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo ERROR: Python .venv tidak ditemukan. Lihat docs\PPE_CAMERA_SETUP.md
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0python\web_cctv_ai.py" --camera 0
pause
