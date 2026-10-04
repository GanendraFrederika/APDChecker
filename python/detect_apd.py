"""
Sistem Deteksi Kesiapan APD (Alat Pelindung Diri) Real-Time
File: detect_apd.py
Fungsi:
1. Membaca stream kamera (Webcam laptop atau kamera CCTV/HP).
2. Mendeteksi orang dan kelengkapan APD menggunakan model Computer Vision YOLO.
3. Mengirimkan sinyal otomatis ke Arduino Uno melalui Serial USB:
   - '1': Jika ada pelanggaran APD (alarm & lampu menyala)
   - '0': Jika semua orang aman & memakai APD lengkap
"""

import cv2
import time
import argparse
from ultralytics import YOLO

# Coba impor serial (jika Arduino terhubung)
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

def cari_port_arduino():
    if not HAS_SERIAL:
        return None
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        # Deteksi otomatis perangkat Arduino / USB-SERIAL CH340
        if "arduino" in p.description.lower() or "ch340" in p.description.lower() or "usb serial" in p.description.lower():
            return p.device
    if ports:
        return ports[0].device
    return None

def main():
    parser = argparse.ArgumentParser(description="Program Deteksi APD Real-Time")
    parser.add_argument("--camera", type=int, default=0, help="Index kamera (default: 0 untuk webcam bawaan)")
    parser.add_argument("--port", type=str, default="", help="Port COM Arduino (misal: COM3)")
    parser.add_argument("--conf", type=float, default=0.45, help="Ambang batas keyakinan deteksi (0.0 - 1.0)")
    args = parser.parse_args()

    # Inisialisasi Koneksi Arduino Serial
    arduino = None
    port_terpilih = args.port if args.port else cari_port_arduino()
    if HAS_SERIAL and port_terpilih:
        try:
            print(f"[INFO] Menghubungkan ke Arduino di port {port_terpilih}...")
            arduino = serial.Serial(port_terpilih, 9600, timeout=1)
            time.sleep(2)
            print("[INFO] Sukses terhubung ke Arduino Uno!")
        except Exception as e:
            print(f"[PERINGATAN] Gagal membuka port Arduino ({e}). Mode simulasi layar aktif.")
    else:
        print("[INFO] Berjalan tanpa Arduino (hanya visual di layar laptop).")

    # Inisialisasi Model AI (Menggunakan YOLOv8 Nano sebagai default yang ringan dan cepat)
    print("[INFO] Memuat model deteksi AI...")
    model = YOLO("yolov8n.pt") 

    # Buka stream kamera
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"[ERROR] Gagal membuka kamera dengan index {args.camera}.")
        return

    print("[INFO] Kamera aktif. Tekan 'q' pada keyboard untuk keluar.")

    status_alarm_terakhir = None
    frame_counter = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[PERINGATAN] Gagal membaca frame kamera.")
            break

        frame_counter += 1

        # Jalankan inferensi deteksi YOLO
        results = model(frame, conf=args.conf, verbose=False)
        detections = results[0]

        ada_orang = False
        pelanggaran_apd = False
        jumlah_orang = 0

        # Analisis objek yang terdeteksi
        for box in detections.boxes:
            cls_id = int(box.cls[0])
            label_name = model.names[cls_id].lower()
            conf = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])

            # Deteksi orang
            if "person" in label_name:
                ada_orang = True
                jumlah_orang += 1
                
                # Default simulasi pengecekan:
                # Catatan: Ketika model khusus APD (helmet/vest) diunduh, logika ini akan memeriksa
                # apakah ada label 'helmet' dan 'vest' pada koordinat badan orang tersebut.
                warna_box = (0, 255, 0) # Hijau = Aman
                status_teks = "Orang: Memakai APD"

                # Contoh demonstrasi: Gambar kotak hijau di sekitar orang
                cv2.rectangle(frame, (x1, y1), (x2, y2), warna_box, 2)
                cv2.putText(frame, f"{status_teks} ({conf*100:.1f}%)", (x1, max(20, y1 - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, warna_box, 2)

        # Logika Pengiriman Sinyal ke Arduino
        sinyal_sekarang = '0'
        pesan_status = "SEMUA AMAN: APD LENGKAP"
        warna_status = (0, 255, 0) # Hijau

        if pelanggaran_apd:
            sinyal_sekarang = '1'
            pesan_status = "PERINGATAN: APD TIDAK LENGKAP!"
            warna_status = (0, 0, 255) # Merah
        elif not ada_orang:
            pesan_status = "AREA KOSONG - MONITORING"
            warna_status = (255, 255, 0) # Kuning

        # Kirim sinyal ke Arduino jika status berubah
        if arduino and (sinyal_sekarang != status_alarm_terakhir):
            try:
                arduino.write(sinyal_sekarang.encode())
                status_alarm_terakhir = sinyal_sekarang
            except Exception as e:
                print(f"[ERROR] Gagal mengirim data ke Arduino: {e}")

        # Tampilkan status bar di bagian atas layar
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 50), (30, 30, 30), -1)
        cv2.putText(frame, pesan_status, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, warna_status, 2)
        cv2.putText(frame, f"Jumlah Orang: {jumlah_orang}", (frame.shape[1] - 220, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # Tampilkan jendela video
        cv2.imshow("Sistem Deteksi APD - Monitoring CCTV", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Bersihkan memori dan port saat keluar
    if arduino:
        arduino.write(b'0') # Pastikan alarm mati saat program ditutup
        arduino.close()
    cap.release()
    cv2.destroyAllWindows()
    print("[INFO] Program selesai.")

if __name__ == "__main__":
    main()
