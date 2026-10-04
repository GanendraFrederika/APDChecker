@echo off
title SISTEM PENGECEK SIAP APD - AI CCTV & ARDUINO
color 0A
echo ===================================================================
echo       SISTEM SENSOR PENGECEK KESIAPAN APD (AI + ARDUINO UNO)
echo ===================================================================
echo.
echo [1/3] Menghubungkan ke Kamera Laptop & Arduino COM3...
echo [2/3] Memulai Server AI CCTV Monitoring di http://localhost:5000...
echo [3/3] Membuka Dashboard di Browser...
echo.

start http://localhost:5000

"C:\Users\ASUS\AppData\Local\Programs\Python\Python311\python.exe" "c:\Users\ASUS\Desktop\APDChecker\python\web_cctv_ai.py"

pause
