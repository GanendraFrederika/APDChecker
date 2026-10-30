# Konversi model ke NPU Pico di VPS Ubuntu (22.04 / 24.04)

Tujuan: mengubah model hasil training (`ppe_project.pt`) menjadi file `.rknn` INT8 yang bisa
dijalankan NPU Luckfox Pico. Alat konversi Rockchip (`rknn-toolkit2`) hanya ada untuk
**Linux**, jadi kita pakai VPS. **Tidak perlu GPU.**

## 1. Spesifikasi VPS

Angka RAM/disk di bawah adalah **perkiraan** (belum diuji di VPS sungguhan).

| Item | Minimal | Disarankan |
|---|---|---|
| OS | Ubuntu 22.04 atau 24.04, **x86_64** (bukan ARM) | Ubuntu 22.04 |
| RAM | 2 GB (+ swap 2 GB) | 4 GB |
| Disk | 10 GB kosong | 20 GB |
| CPU | 1 vCPU | 2 vCPU |
| Akses | SSH + `sudo` | |

Ubuntu 22.04 sedikit lebih aman: Python 3.10 adalah versi yang paling lama didukung
`rknn-toolkit2`. 24.04 (Python 3.12) juga didukung; skrip memilih paket yang benar otomatis.

## 2. Upload file dari laptop ke VPS

Di **laptop Windows** (PowerShell), dari folder `APDChecker`:

```powershell
# 1) foto kalibrasi (200 foto, foto bengkel diutamakan)
.venv\Scripts\python.exe scripts\make_rknn_calib.py --count 200

# 2) kirim semua ke VPS (ganti IP-VPS); scp sudah ada di Windows 10/11
ssh root@IP-VPS "mkdir -p ~/apd"
scp edge\luckfox\rknn\setup_rknn.sh edge\luckfox\rknn\export_rknn.sh edge\luckfox\rknn\constraints-ubuntu2204.txt edge\luckfox\rknn\constraints-ubuntu2404.txt root@IP-VPS:~/apd/
scp datasets\rknn_calib.zip models\ppe_helmet_vest.pt root@IP-VPS:~/apd/
```

Setelah training selesai, kirim juga `models\ppe_project.pt` dengan cara yang sama.
(Kalau login VPS bukan `root`, ganti `root@` dengan nama user-nya.)

## 3. Siapkan VPS (sekali saja, ±10 menit)

```bash
ssh root@IP-VPS
cd ~/apd

# swap 2 GB (aman walau RAM VPS cuma 2 GB; lewati kalau RAM >= 4 GB)
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile

bash setup_rknn.sh
```

Berhasil kalau baris terakhir berbunyi:
`OK  rknn-toolkit2 siap | ultralytics 8.4.175 | torch 2.4.0+cpu | ... | numpy 1.26.4`

## 4. Konversi (setiap ada model baru, ±2-5 menit)

```bash
cd ~/apd
# uji coba dulu dengan model yang sudah ada:
bash export_rknn.sh ppe_helmet_vest.pt rknn_calib.zip 320
# model hasil training sendiri:
bash export_rknn.sh ppe_project.pt rknn_calib.zip 320
```

Hasilnya `ppe_project_rknn_model.zip` (isi: file `.rknn`, `metadata.yaml`, `SHA256SUMS`).
Unduh ke laptop (PowerShell):

```powershell
scp root@IP-VPS:~/apd/ppe_project_rknn_model.zip models\
```

- `320` = ukuran input model. 320 cepat untuk RV1103. 416 lebih teliti untuk orang yang jauh,
  tapi lebih lambat dan butuh memori NPU lebih banyak.
- Argumen ke-4 adalah chip: `rv1103` (default, Pico Mini B) atau `rv1106` (Pico Pro/Max/Ultra).

## 5. Kenapa versi paketnya dikunci (penting kalau mau mengubah skrip)

Semua versi di `constraints-ubuntu2204.txt` / `constraints-ubuntu2404.txt` sudah dicek saling cocok
(metadata PyPI dan PyTorch, 30-10-2026). Jangan `pip install -U` di venv ini.

| Paket | Versi | Alasan |
|---|---|---|
| rknn-toolkit2 | 2.3.2 | versi minimal yang didukung ultralytics untuk ekspor RKNN |
| numpy | 1.26.4 | rknn-toolkit2 menolak numpy 2.x |
| protobuf | 4.25.4 | batas atas rknn-toolkit2 |
| torch / torchvision | 2.4.0+cpu / 0.19.0+cpu | rknn butuh torch ≤ 2.4.0; versi CPU menghemat beberapa GB |
| opencv-python | 4.11.0.86 | versi terakhir yang masih menerima numpy 1.x |
| onnx | 1.17.0 | ultralytics butuh < 1.19, rknn butuh ≥ 1.16.1 |
| onnxruntime | 1.19.2 (22.04) / 1.20.1 (24.04) | 1.27+ menuntut protobuf ≥ 4.25.8 (bentrok) |
| onnxslim + ml-dtypes | 0.1.98 + 0.5.4 | ml-dtypes 0.6 menuntut numpy 2 |
| setuptools | 81.0.0 | rknn-toolkit2 masih memakai `pkg_resources` (dihapus di 82) |

Skrip juga mengekspor `PIP_CONSTRAINT`/`UV_CONSTRAINT` dan mematikan instalasi otomatis ultralytics
saat ekspor (`ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS=1`), supaya tidak ada yang menaikkan numpy di
tengah jalan. Kalau ekspor mengeluh paket hilang, jalankan ulang `setup_rknn.sh`.

## 6. Kalau gagal

| Pesan | Penyebab dan solusi |
|---|---|
| `Killed` saat setup/ekspor | RAM habis: buat swap (langkah 3) |
| `externally-managed-environment` | pip dijalankan di luar venv: jalankan ulang lewat skrip, bukan `pip` sistem |
| `ImportError: libGL.so.1` | `sudo apt-get install -y libgl1` |
| `No module named pkg_resources` | setuptools terlalu baru: `pip install setuptools==81.0.0` di venv |
| `ResolutionImpossible` | Jangan ubah versi di file constraints satu per satu |
| Ekspor jalan tapi model gagal di Pico | Lihat bagian 7 di dokumen ini (versi runtime) |

## 7. Catatan versi runtime di Pico (belum teruji)

Pico Mini B kita masih membawa `librknnmrt` **1.4.1b9 (2022)** dan driver NPU **v0.8.2**. Model dari
toolkit 2.3.2 kemungkinan besar butuh runtime 2.3.2. Rencananya: bawa `librknnmrt.so` versi 2.3.2
(`rknpu2/runtime/Linux/librknn_api/armhf-uclibc/` di repo `airockchip/rknn-toolkit2`, tag `v2.3.2`)
bersama program kita lewat `LD_LIBRARY_PATH`, **tanpa menimpa file sistem**. Apakah runtime 2.3.2 mau
jalan di driver v0.8.2 baru ketahuan saat dites. Kalau tidak bisa, jalan keluarnya flash image resmi
Luckfox terbaru (`Luckfox_Pico_Mini_B_Flash_250313`, SDK cabang `main`, kernel 5.10.160). Kecocokan
runtime di image itu dengan toolkit 2.3.2 **juga belum diverifikasi**, dan flash menghapus semua isi
Pico: lakukan backup lengkap dulu (`STANDALONE_PICO.md` bagian 2c).
