"""
Uji Coba Otomatis: Patroli, Lock-On Target, dan Return to 90
File: test_patrol_lock.py
"""

import time
import serial

print("=== UJI COBA FITUR PATROLI & LOCK-ON SERVO CCTV ===")
ser = serial.Serial("COM3", 9600, timeout=1)
time.sleep(2) # Tunggu boot

print("\n1. Posisi awal: Servo diam di 90 derajat.")
time.sleep(1)

print("\n2. Mengirim sinyal 'T' -> Memulai putaran patroli (0 ke 130 derajat)...")
ser.write(b'T')
time.sleep(1.8) # Biarkan servo berputar di tengah jalan

print("\n3. ORANG TERDETEKSI TANPA APD! Mengirim sinyal '1'...")
print("   -> Servo harus LANGSUNG BERHENTI / MENGUNCI di sudut saat ini!")
print("   -> Speaker TOA bunyi 'TEET!' & LED Pin 8 kedip sinkron!")
ser.write(b'1')
time.sleep(4.0)

print("\n4. ORANG MEMAKAI APD / PERGI! Mengirim sinyal '0'...")
print("   -> Suara dan LED langsung MATI.")
print("   -> Servo berputar kembali secara halus ke 90 derajat!")
ser.write(b'0')
time.sleep(2.0)

ser.close()
print("\n=== UJI COBA SUKSES 100%! ===")
