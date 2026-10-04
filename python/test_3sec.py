import time
import serial

ser = serial.Serial("COM3", 9600, timeout=1)
time.sleep(1.8)
print(">>> [ALARM ON] Membunyikan suara bass 'TETT' & LED Pin 8 menyala...")
ser.write(b'1')
time.sleep(10.0)
print(">>> [ALARM OFF] Mematikan suara dan LED...")
ser.write(b'0')
time.sleep(0.2)
ser.close()
print(">>> Selesai 3 detik!")
