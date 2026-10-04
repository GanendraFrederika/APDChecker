import cv2
import sys

print("Mencoba menangkap gambar dari kamera...")
backends = [
    ("CAP_DSHOW", cv2.CAP_DSHOW),
    ("CAP_MSMF", cv2.CAP_MSMF),
    ("DEFAULT", 0)
]

sukses = False
for name, be in backends:
    print(f"Mencoba backend: {name}...")
    cap = cv2.VideoCapture(0, be) if be != 0 else cv2.VideoCapture(0)
    if cap.isOpened():
        # Baca beberapa frame agar sensor kamera stabil
        for _ in range(5):
            ret, frame = cap.read()
        cap.release()
        if ret and frame is not None and frame.size > 0:
            output_file = r"c:\Users\ASUS\Desktop\APDChecker\camera_snapshot.jpg"
            cv2.imwrite(output_file, frame)
            print(f"[BERHASIL] Gambar berhasil diambil via {name}!")
            print(f"Resolusi: {frame.shape[1]}x{frame.shape[0]}")
            print(f"File tersimpan di: {output_file}")
            sukses = True
            break
        else:
            print(f"[{name}] Kamera terbuka tapi frame kosong.")
    else:
        print(f"[{name}] Kamera gagal dibuka.")

if not sukses:
    print("[GAGAL] Tidak dapat mengambil gambar dari kamera 0.")
