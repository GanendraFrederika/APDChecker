"""
Uji Coba Kamera Laptop / Webcam (DirectShow Backend)
File: test_camera.py
"""

import cv2
import time

def test_camera():
    print("Mencoba membuka kamera dengan backend DirectShow (CAP_DSHOW)...")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

    # Atur resolusi standar agar stabil
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print("[GAGAL] Kamera dengan index 0 tidak bisa dibuka dengan DirectShow.")
        print("Mencoba backend default...")
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("[GAGAL TOTAL] Kamera tidak dapat diakses. Pastikan izin kamera aktif di Settings Windows.")
        return

    # Beri waktu sensor kamera menyesuaikan pencahayaan
    time.sleep(1)

    print("[BERHASIL] Kamera terhubung! Menampilkan jendela video...")
    print("Tekan tombol 'q' di jendela video untuk keluar.\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[PERINGATAN] Frame kosong, mencoba membaca ulang...")
            time.sleep(0.1)
            continue

        # Tambahkan teks informasi
        cv2.putText(
            frame, 
            "Tes Kamera APD - Tekan 'q' untuk keluar", 
            (20, 30), 
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.7, 
            (0, 255, 0), 
            2
        )

        cv2.imshow("Kamera Laptop APD Checker", frame)

        # Keluar jika tombol 'q' ditekan
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Kamera ditutup dengan sukses.")

if __name__ == "__main__":
    test_camera()
