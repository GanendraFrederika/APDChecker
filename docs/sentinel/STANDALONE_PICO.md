# Standalone di Pico (tanpa laptop): rencana dan command

Status 30-10-2026: **belum jalan**. Pico saat ini hanya kamera. AI berjalan di laptop.
Dokumen ini memuat langkah dan command yang sudah dicek terhadap board kita.

## Fakta board (dibaca dari Pico lewat ADB)

| Item | Nilai |
|---|---|
| Board / SoC | Luckfox Pico Mini B, RV1103, NPU 0,5 TOPS INT8 |
| OS | Linux 5.10.110, **uClibc** (bukan glibc), ARM 32-bit hard-float |
| Driver NPU | RKNPU **v0.8.2** |
| Runtime NPU | `librknnmrt.so` **1.4.1b9** (2022) |
| RAM | 33,5 MB total, ±9 MB bebas saat kamera menyala |
| Disk | rootfs 99% penuh; `/oem` sisa ±4,8 MB; `/userdata` ±4,4 MB |
| UART3 | pin 12 TX, pin 13 RX (3,3 V) |

**Konsekuensi penting:** model yang dikonversi dengan rknn-toolkit2 2.x harus dijalankan
dengan `librknnmrt.so` dari rilis yang sama (2.3.2, folder `armhf-uclibc`). Library itu
kita bawa sendiri (`LD_LIBRARY_PATH`) dan **tidak menimpa file sistem**. Kecocokannya dengan
driver v0.8.2 belum diuji: itu tes pertama di Pico. Kalau gagal, pilihannya flash image
Luckfox terbaru (bisa kehilangan pengaturan kamera sekarang, jadi backup dulu).

## Tahap 1: konversi model di server Linux (Pterodactyl)

Server harus: Linux x86_64 atau ARM64, Python **3.10 atau 3.11**, RAM ≥ 4 GB, disk ≥ 10 GB.
Pakai egg Python/generic Linux yang memberi akses console. Upload file lewat File Manager panel:

1. `edge/luckfox/rknn/setup_rknn.sh`
2. `edge/luckfox/rknn/export_rknn.sh`
3. model `.pt` (hasil training, `ppe_project.pt`)
4. `datasets/rknn_calib.zip` (buat di Windows: `scripts\make_rknn_calib.py`)

Lalu di console server:

```bash
bash setup_rknn.sh                                   # sekali saja, ±5-10 menit
bash export_rknn.sh ppe_project.pt rknn_calib.zip 320
```

Hasil: `ppe_project_rknn_model.zip` berisi `.rknn` INT8 untuk `rv1103`. Unduh lewat File Manager.

## Tahap 2: program di Pico (belum ditulis)

Butuh toolchain `arm-rockchip830-linux-uclibcgnueabihf` dari SDK Luckfox (Linux x86_64).
Program C: ambil frame (RKMPI VI) → resize 320 → NPU → decode kotak → keputusan APD →
kirim frame `S` SLP/1.1 lewat UART3 ke Arduino. Contoh resmi untuk dasar:
`LuckfoxTECH/luckfox_pico_rknn_example` (yolov5) dan `luckfox_pico_rkmpi_example`.

## Batasan (sudah disepakati pemilik)

- Hanya deteksi orang + helm + rompi + sepatu. Tanpa pose 17 titik dan tanpa gestur.
- Kecepatan target 3-5 fps pada 320 px. Belum diukur.
- Laptop tetap dipakai untuk pameran/dashboard sampai versi standalone teruji.
