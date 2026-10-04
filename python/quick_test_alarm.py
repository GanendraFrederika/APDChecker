"""
Uji Coba Cepat Alarm & Speaker TPA3110 (Versi Suara Lembut)
File: quick_test_alarm.py
Fungsi:
1. Otomatis menghubungkan ke Arduino di COM3
2. Mengirim sinyal '1' (ALARM ON) selama 4 detik -> Speaker bunyi sirine pelan & LED pin 13 nyala
3. Mengirim sinyal '0' (SAFE) -> Suara sirine mati & LED mati
"""

import sys
import time
import serial

# Pastikan output teks aman di Windows terminal
if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PORT = "COM3"
BAUD = 9600

def test():
    print(f"[1/4] Menghubungkan ke Arduino di {PORT}...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=2)
    except Exception as e:
        print(f"[GAGAL] Tidak dapat membuka {PORT}: {e}")
        return

    # Tunggu inisialisasi reset Arduino
    time.sleep(2)
    print("[2/4] Terhubung! Mengirim sinyal: ALARM ON ('1')...")
    ser.write(b'1')
    time.sleep(0.1)

    if ser.in_waiting > 0:
        print(f"      Balasan Arduino: {ser.readline().decode('utf-8', errors='ignore').strip()}")

    print("      -> Sirine sedang aktif dengan volume lembut (level 3)")
    print("      -> Menunggu 4 detik...")
    time.sleep(4)

    print("[3/4] Mengirim sinyal: ALARM OFF / SAFE ('0')...")
    ser.write(b'0')
    time.sleep(0.1)

    if ser.in_waiting > 0:
        print(f"      Balasan Arduino: {ser.readline().decode('utf-8', errors='ignore').strip()}")

    ser.close()
    print("[4/4] Selesai! Alarm telah dimatikan.")

if __name__ == "__main__":
    test()
