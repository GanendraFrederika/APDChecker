import urllib.request
import os
import sys

def download_model():
    target_dir = r"c:\Users\ASUS\Desktop\APDChecker\models"
    os.makedirs(target_dir, exist_ok=True)
    target_file = os.path.join(target_dir, "ppe_yolov8n.pt")

    # URL HuggingFace model publik untuk PPE detection (Hardhat, Vest, etc.)
    urls = [
        "https://huggingface.co/keremberke/yolov8n-protective-equipment-detection/resolve/main/best.pt",
        "https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt"
    ]

    for url in urls:
        print(f"Mencoba mengunduh dari: {url}")
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=60) as response, open(target_file, 'wb') as out_file:
                total_size = int(response.info().get('Content-Length', 0))
                downloaded = 0
                block_size = 1024 * 64

                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    downloaded += len(buffer)
                    out_file.write(buffer)
                    if total_size > 0:
                        percent = downloaded * 100 / total_size
                        sys.stdout.write(f"\rProgress: {percent:.1f}% ({downloaded / 1024 / 1024:.2f} MB)")
                        sys.stdout.flush()

            print(f"\n[SUKSES] File tersimpan di: {target_file}")
            print(f"Ukuran file: {os.path.getsize(target_file) / 1024 / 1024:.2f} MB")
            return target_file
        except Exception as e:
            print(f"\n[GAGAL] {e}")

    return None

if __name__ == "__main__":
    download_model()
