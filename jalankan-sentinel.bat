@echo off
setlocal
cd /d "%~dp0"
title APD Sentinel
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Python .venv tidak ditemukan. Lihat README bagian "Instalasi baru".
  pause
  exit /b 1
)
echo APD Sentinel: kamera Pico + AI + Arduino.
echo Dashboard: http://127.0.0.1:8080  (terbuka otomatis sebentar lagi)
echo Tekan Ctrl+C di jendela ini untuk berhenti.
echo.
start "" /b cmd /c "timeout /t 25 /nobreak >nul & start "" http://127.0.0.1:8080"
cd python
"..\.venv\Scripts\python.exe" -m sentinel.app --camera luckfox --port auto %*
if errorlevel 1 pause
