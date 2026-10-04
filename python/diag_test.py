import time
import serial

print("1. Membuka COM3...")
ser = serial.Serial("COM3", 9600, timeout=2)

print("2. Menunggu Arduino Boot...")
# Baca semua pesan boot dari Arduino
start = time.time()
while time.time() - start < 3:
    line = ser.readline().decode('utf-8', errors='ignore').strip()
    if line:
        print(f"   [Arduino Boot] {line}")
        if "READY" in line:
            break

print("3. Mengirim perintah '1' (ALARM ON)...")
ser.write(b'1')
time.sleep(0.5)

# Baca respon
while ser.in_waiting > 0:
    print(f"   [Arduino Respon] {ser.readline().decode('utf-8', errors='ignore').strip()}")

print("4. Menunggu 4 detik alarm berbunyi...")
for s in range(4):
    print(f"   Detik {s+1}...")
    time.sleep(1)
    while ser.in_waiting > 0:
        print(f"   [Arduino Log] {ser.readline().decode('utf-8', errors='ignore').strip()}")

print("5. Mengirim perintah '0' (ALARM OFF)...")
ser.write(b'0')
time.sleep(0.5)
while ser.in_waiting > 0:
    print(f"   [Arduino Respon] {ser.readline().decode('utf-8', errors='ignore').strip()}")

ser.close()
print("Selesai!")
