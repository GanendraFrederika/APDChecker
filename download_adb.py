import urllib.request
import zipfile
import os

url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
zip_path = r"c:\Users\ASUS\Desktop\APDChecker\platform-tools.zip"
dest_dir = r"c:\Users\ASUS\Desktop\APDChecker"

print("Mengunduh Android Platform Tools via Python...")
urllib.request.urlretrieve(url, zip_path)
print("Mengekstrak file ZIP...")
with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall(dest_dir)

if os.path.exists(zip_path):
    os.remove(zip_path)

adb_path = os.path.join(dest_dir, "platform-tools", "adb.exe")
if os.path.exists(adb_path):
    print("[SUKSES] ADB berhasil diinstall di:", adb_path)
else:
    print("[GAGAL] adb.exe tidak ditemukan.")
