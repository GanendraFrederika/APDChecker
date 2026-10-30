# Standalone di Pico (tanpa laptop): sistem operasi, memori, dan pilihan chip

Status 30-10-2026: **belum jalan**. Pico saat ini hanya kamera; AI berjalan di laptop.
Angka di bagian 1 dibaca langsung dari board kita lewat ADB. Spesifikasi chip dicek dari sumber
resmi (rock-chips.com, wiki.luckfox.com, GitHub LuckfoxTECH dan airockchip) pada 30-10-2026.
Yang ditandai *perkiraan* belum diukur.

## 1. Board kita sekarang

| Item | Nilai (dibaca dari Pico) |
|---|---|
| Board / chip | Luckfox Pico Mini B, **RV1103**, NPU 0,5 TOPS (INT8) |
| OS | **Buildroot 2023.02.6**, kernel 5.10.110, ARM 32-bit, uClibc |
| RAM fisik | 64 MB DDR2 di dalam chip (tidak bisa ditambah) |
| RAM untuk Linux | 33,5 MB. **24 MB lainnya dipakai CMA** (memori khusus kamera + NPU) |
| Saat kamera menyala | CMA bebas **0 MB**, RAM bebas ±9 MB |
| Runtime NPU | `librknnmrt` 1.4.1b9 (2022), driver RKNPU v0.8.2 |
| Pemakan RAM terbesar | rkipc (kamera) ±9 MB, Samba (berbagi file) ±4,3 MB |

## 2. Pakai Buildroot? Ya. **Kita memang sudah pakai Buildroot.**

- Untuk Pico Mini B (RV1103, SPI NAND), **Buildroot adalah satu-satunya OS resmi** dan yang
  paling ringan. Ubuntu hanya tersedia sebagai image pihak ketiga untuk microSD, dan dengan
  64 MB RAM tidak realistis.
- Jadi bukan "pindah ke Buildroot", melainkan **merampingkan Buildroot yang sudah ada**.

### 2a. Rampingkan tanpa flash ulang (aman, bisa dibatalkan)

Buildroot hanya menjalankan skrip `/etc/init.d/S??*` saat boot. Cukup **ganti nama** skrip yang
tidak perlu (dibatalkan dengan mengembalikan namanya):

```sh
adb shell
/etc/init.d/S91smb stop && mv /etc/init.d/S91smb /etc/init.d/_S91smb        # Samba: hemat ±4,3 MB
mv /etc/init.d/S50telnet /etc/init.d/_S50telnet                               # telnet tanpa sandi
cat /etc/init.d/S99hciinit       # baca dulu; ganti nama hanya kalau isinya cuma inisialisasi Bluetooth:
# mv /etc/init.d/S99hciinit /etc/init.d/_S99hciinit
cat /etc/init.d/S99_auto_reboot     # baca dulu: kalau me-reboot berkala, nonaktifkan juga
reboot
```

Setelah reboot cek dengan `free` dan `grep -E 'MemAvailable|Cma' /proc/meminfo`.
Kita tetap punya `adb` (dan `ssh`) untuk masuk ke Pico.

### 2b. Atur CMA (butuh build SDK, lalu flash `env.img` saja)

CMA 24 MB dibagi antara kamera dan NPU. Saat ini kamera (rkipc) menghabiskan semuanya. Untuk
standalone, **kamera dijalankan dengan resolusi lebih kecil oleh program kita sendiri** supaya
CMA tersisa untuk NPU (cara yang disarankan, tanpa flash). Ukuran CMA sendiri diatur di file board
SDK (`RK_BOOTARGS_CMA_SIZE="24M"`, dibuat dengan `./build.sh env`). Menaikkan CMA mengurangi RAM
Linux dengan jumlah yang sama.

**Belum diuji:** flash *hanya* `env.img`. File itu juga berisi tabel partisi, yang berbeda antar
cabang SDK (5.10.110 vs main). Sebelum mencoba: bandingkan `adb shell cat /proc/cmdline` (bagian
`mtdparts=` dll.) dengan bootargs di `env.img` baru: **hanya** `rk_dma_heap_cma` yang boleh berbeda.
Kalau board gagal boot, pemulihannya flash `update.img` penuh (menghapus semua: backup dulu, 2c).

### 2c. Build image sendiri (lengkap, di VPS/PC Ubuntu 22.04 x86_64)

```bash
sudo apt-get install -y git ssh make gcc gcc-multilib g++-multilib module-assistant expect g++ gawk \
  texinfo libssl-dev bison flex fakeroot cmake unzip gperf autoconf device-tree-compiler \
  libncurses5-dev pkg-config bc python-is-python3 passwd openssl openssh-server openssh-client \
  vim file cpio rsync curl
# cabang yang sama dengan kernel di board kita (5.10.110); "main" = kernel 5.10.160 (lebih baru)
git clone --depth 1 --single-branch -b 5.10.110 https://github.com/LuckfoxTECH/luckfox-pico.git
cd luckfox-pico
cd tools/linux/toolchain/arm-rockchip830-linux-uclibcgnueabihf && source env_install_toolchain.sh && cd ../../../..
./build.sh lunch          # pilih: Luckfox Pico Mini (B) -> SPI_NAND -> Buildroot
./build.sh buildrootconfig   # opsional: buang paket (Samba, Python, dll.)
./build.sh                # hasil: output/image/update.img (+ image per partisi)
```

- Jangan build dengan `sudo`. Di WSL2, kerjakan di `~/` (bukan `/mnt/c` atau `/mnt/d`).
- **Flash** (Windows): pasang *RK Driver Assistant*, buka *SocToolKit* (sebagai Administrator, pilih
  chip **RV1106**, ini benar juga untuk RV1103), tahan tombol **BOOT** sambil mencolok USB
  (atau `adb shell reboot loader`), lalu *Firmware* → `update.img` → *Upgrade*.
- **Flash `update.img` menimpa SEMUA partisi** (env, uboot, boot, oem, rootfs, userdata). Profil
  kamera kita, skrip guard, perubahan di bagian 2a, dan pengaturan lain hilang. Backup lengkap dulu
  (dari PowerShell, di folder `APDChecker`):
  ```powershell
  mkdir backup-pico; cd backup-pico
  ..\platform-tools\adb.exe pull /oem oem
  ..\platform-tools\adb.exe pull /userdata userdata
  ..\platform-tools\adb.exe pull /etc etc
  ..\platform-tools\adb.exe shell "cat /proc/cmdline; cat /proc/mtd" > cmdline-mtd.txt
  ```
  Setelah flash, perubahan bagian 2a harus diulang.

## 3. Konversi model

Lihat `docs/sentinel/VPS_RKNN.md` (VPS Ubuntu 22.04/24.04, skrip siap pakai).

## 4. Program di Pico (belum ditulis)

Bahasa C dengan toolchain `arm-rockchip830-linux-uclibcgnueabihf` dari SDK. Alurnya:
kamera (RKMPI, resolusi kecil) → resize 320 → NPU → kotak helm/rompi/sepatu/orang →
keputusan APD → kirim frame `S` SLP/1.1 lewat UART3 ke Arduino. Dasar: contoh resmi
`LuckfoxTECH/luckfox_pico_rknn_example` (cabang `kernel-5.10.110` untuk board kita) dan
`luckfox_pico_rkmpi_example`. Python tidak dipakai di Pico (RAM tidak cukup).

## 5. Perbandingan chip Rockchip seri RV

Kemampuan dinilai untuk **aplikasi kita**: kamera + deteksi APD (helm, rompi, sepatu, orang) di board.

| Chip | CPU | RAM | NPU | Board Luckfox | Deteksi APD di board | Pose 17 titik di board | Penilaian |
|---|---|---|---|---|---|---|---|
| **RV1103** (punya kita) | 1× Cortex-A7 1,2 GHz | 64 MB DDR2 (di chip) | 0,5 TOPS | Pico, Mini A, **Mini B**, Plus, WebBee | Didukung (terbatas). *Perkiraan:* input kecil (320), kamera beresolusi rendah, C saja | Tidak | **Cukup** |
| RV1103B | 1× Cortex-A7 | 64-256 MB (di chip) | 0,5 TOPS | belum ada | Belum ada contoh resmi (dukungan beta) | Tidak | Belum disarankan |
| **RV1106G2** | 1× Cortex-A7 1,2 GHz | 128 MB DDR3L (di chip) | 0,5 TOPS | **Pico Pro**, Ultra B/BW, Pi B | Bisa, lebih lega; demo kamera+YOLO resmi tersedia | Tidak (resmi) | **Kuat** |
| **RV1106G3** | 1× Cortex-A7 1,2 GHz | 256 MB DDR3L (di chip) | 1 TOPS | **Pico Max**, Ultra, Ultra W, Zero, Pi A | Didukung (terbatas). *Perkiraan:* nyaman, input lebih besar (416-640) | Tidak (resmi) | **Kuat** |
| RV1106B | 1× Cortex-A7 | 64-256 MB (di chip) | tidak dipublikasikan | belum ada | Belum ada contoh resmi | Tidak | Belum disarankan |
| RV1109 | 2× Cortex-A7 | RAM eksternal | 1,2 TOPS | tidak ada | Toolkit lama (v1), tidak bisa diekspor ultralytics | Tidak | Usang |
| RV1126 | 4× Cortex-A7 | RAM eksternal | 2 TOPS | tidak ada | Toolkit lama (v1), tidak bisa diekspor ultralytics | Tidak | Usang |
| **RV1126B** | 4× Cortex-A53 64-bit 1,6 GHz | 1 / 2 / 4 GB LPDDR4X | 3 TOPS | **Aura** | Sangat lancar (yolov8n ±83 fps @640, INT8, angka resmi) | **Ya** (±59 fps INT8 resmi via rknn_model_zoo; ekspor ultralytics untuk pose hanya FP16, fps belum diukur) | **Sangat kuat** |

Keterangan:
- **Cukup** = bisa jalan dengan banyak kompromi (resolusi kecil, tanpa pose/gestur, kode C).
- **Kuat** = deteksi APD standalone yang nyaman, kode program sama dengan Mini B (SDK sama).
- **Sangat kuat** = deteksi + pose + Python langsung di board (Linux 64-bit, bisa Debian).
- Angka fps resmi hanya dipublikasikan Rockchip untuk RV1126B (dan chip lama). Untuk
  RV1103/RV1106 Rockchip menyebut dukungannya "limited" dan tidak memberi angka fps:
  harus diukur sendiri.
- RV1103B dan RV1106B adalah chip baru (Des 2025) dengan dukungan software yang belum matang.

**Saran upgrade:**
1. Ingin tetap pakai program dan SDK yang sama: **Luckfox Pico Max** (RV1106G3, 256 MB, 1 TOPS).
   Atau **Pico Ultra W** kalau ingin eMMC, PoE, dan Wi-Fi. RAM 4× dan NPU 2× dibanding Mini B.
2. Ingin pose dan gestur ikut jalan tanpa laptop: **Luckfox Aura** (RV1126B).
3. Tetap Mini B: bisa, asal menerima batasan (deteksi saja, 320 px; kecepatan belum diukur).

Harga tidak dicantumkan karena berubah-ubah; cek di toko resmi Luckfox atau distributor.
