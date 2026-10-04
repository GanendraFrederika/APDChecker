"""
Uji Coba 10 Detik: Alarm Horn TOA + LED Kedip Sinkron
File: test_10sec.py
Fungsi:
1. Membuka koneksi Serial ke Arduino di COM3
2. Mengirim perintah '1' (ALARM ON)
3. Membiarkan alarm dan LED berkedip sinkron selama 10 detik
4. Mengirim perintah '0' (SAFE) untuk mematikan alarm seketika
"""

import sys
import time
import serial

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

    # Tunggu reset bootloader
    print("[2/4] Menunggu Arduino siap...")
    start = time.time()
    while time.time() - start < 3:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"      [Arduino Boot] {line}")
            if "READY" in line:
                break

    print("[3/4] Mengirim sinyal: ALARM ON ('1')...")
    ser.write(b'1')
    time.sleep(0.2)

    while ser.in_waiting > 0:
        print(f"      [Arduino Respon] {ser.readline().decode('utf-8', errors='ignore').strip()}")

    print("\n>>> ALARM DAN LED AKTIF SELAMA 10 DETIK <<<")
    print("Perhatikan: Suara horn TOA dan LED Pin 8 harus berkedip bersamaan seirama!\n")

    for s in range(10, 0, -1):
        print(f"      Hitung mundur: {s} detik...")
        time.sleep(1)

    print("\n[4/4] Waktu habis! Mengirim sinyal: ALARM OFF / SAFE ('0')...")
    ser.write(b'0')
    time.sleep(0.5)

    while ser.in_waiting > 0:
        print(f"      [Arduino Respon] {ser.readline().decode('utf-8', errors='ignore').strip()}")

    ser.close()
    print("\n[SELESAI] Suara TOA dan LED telah dimatikan seketika!")

if __name__ == "__main__":
    test()
