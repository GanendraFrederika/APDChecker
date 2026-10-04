import cv2

print("=== MEMINDAI SEMUA KAMERA DI SISTEM ===")
ditemukan = 0
for i in range(5):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        ret, frame = cap.read()
        if ret and frame is not None and frame.size > 0:
            h, w = frame.shape[:2]
            print(f"[KAMERA INDEX {i}] TERDETEKSI AKTIF! Resolusi: {w}x{h}")
            cv2.imwrite(rf"c:\Users\ASUS\Desktop\APDChecker\camera_test_index_{i}.jpg", frame)
            ditemukan += 1
        else:
            print(f"[KAMERA INDEX {i}] Terbuka tapi frame kosong.")
        cap.release()

print(f"Total kamera aktif ditemukan: {ditemukan}")
