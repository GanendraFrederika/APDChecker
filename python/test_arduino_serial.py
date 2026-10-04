"""
Uji Coba Komunikasi Serial Laptop ➔ Arduino Uno
File: test_arduino_serial.py
Fungsi: Memindai port COM Arduino dan mengirim sinyal uji coba Alarm ('1' / '0').
"""

import time
import serial
import serial.tools.list_ports

def scan_ports():
    ports = list(serial.tools.list_ports.comports())
    print("\n--- Port COM Terdeteksi ---")
    if not ports:
        print("Tidak ada port COM yang terdeteksi. Pastikan kabel USB Arduino sudah dicolok!")
        return None

    for i, port in enumerate(ports):
        print(f"[{i + 1}] {port.device} - {port.description}")
    return ports

def main():
    ports = scan_ports()
    if not ports:
        return

    pilihan = input("\nPilih nomor port Arduino (misal: 1): ")
    try:
        idx = int(pilihan) - 1
        port_name = ports[idx].device
    except (ValueError, IndexError):
        print("Pilihan nomor port tidak valid.")
        return

    print(f"Menghubungkan ke {port_name} dengan baudrate 9600...")
    try:
        ser = serial.Serial(port_name, 9600, timeout=2)
        time.sleep(2) # Menunggu inisialisasi reset Arduino Uno saat koneksi serial terbuka
        print("[TERHUBUNG] Berhasil terhubung ke Arduino Uno!")
        print("\nPetunjuk:")
        print("Ketik '1' lalu Enter: Nyalakan Alarm & Lampu")
        print("Ketik '0' lalu Enter: Matikan Alarm & Lampu")
        print("Ketik 'q' lalu Enter: Keluar dari program\n")

        while True:
            cmd = input("Kirim Perintah (1/0/q): ").strip()
            if cmd.lower() == 'q':
                break
            elif cmd in ['1', '0']:
                ser.write(cmd.encode())
                time.sleep(0.1)
                # Baca balasan dari Arduino jika ada
                if ser.in_waiting > 0:
                    balasan = ser.readline().decode('utf-8', errors='ignore').strip()
                    print(f"Balasan Arduino: {balasan}")
            else:
                print("Perintah tidak dikenal. Masukkan '1', '0', atau 'q'.")

        ser.close()
        print("Koneksi serial ditutup.")
    except Exception as e:
        print(f"[ERROR] Gagal membuka port {port_name}: {e}")

if __name__ == "__main__":
    main()
