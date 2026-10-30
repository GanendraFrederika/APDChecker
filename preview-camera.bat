@echo off
setlocal
cd /d "%~dp0"
title APD Sentinel - Preview Kamera
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Python .venv tidak ditemukan. Lihat README bagian "Instalasi baru".
  pause
  exit /b 1
)
echo Preview kamera untuk meluruskan / memutar kamera (tanpa AI, ringan).
echo Jendela preview terbuka di tengah layar. Tutup jendela itu untuk berhenti.
echo.
".venv\Scripts\python.exe" scripts\preview_camera.py %*
if errorlevel 1 pause
