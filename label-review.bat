@echo off
setlocal
cd /d "%~dp0"
title APD Sentinel - Periksa Label
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Python .venv tidak ditemukan. Lihat README bagian "Instalasi baru".
  pause
  exit /b 1
)
echo Periksa label foto bengkel (datasets\workshop). Semua perubahan langsung tersimpan.
echo Tutup jendela pemeriksa untuk berhenti.
echo.
".venv\Scripts\python.exe" scripts\label_review.py %*
if errorlevel 1 pause
