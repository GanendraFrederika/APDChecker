@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Tidak ada interpreter .venv. Lihat docs\luckfox\README.md.
  pause
  exit /b 1
)
echo TEST OFFLINE - tidak mengakses Luckfox, kamera, atau Arduino.
"%PY%" "%ROOT%scripts\test_apd_offline.py"
if errorlevel 1 goto failed
"%PY%" "%ROOT%scripts\check_apd_offline.py" --replay "%ROOT%tests\fixtures\apd_replay.jsonl"
if errorlevel 1 goto failed
echo Selesai. Replay SINTETIS, bukan uji akurasi kamera. Relay tetap nonaktif.
pause
exit /b 0
:failed
echo Pengujian gagal. Jangan dianggap SAFE atau siap deployment.
pause
exit /b 1
