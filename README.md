# APD Sentinel — Kamera Pengecek APD yang Mengunci Orang

Prototipe CCTV pintar untuk bengkel. Kamera **mencari orang, mengunci dan mengikuti orang itu
dengan servo, lalu mengecek APD-nya** (helm, rompi, sepatu). Kalau ada
APD yang kurang, kamera **tetap mengunci orang tersebut** dan alarm berbunyi. Robot juga bisa
diajak berinteraksi: angguk saat diberi jempol, geleng kalau APD-nya masih kurang, dan menyapa
saat orang melambai.

> Status: **prototipe pengembangan** (Oktober 2026). Bukan sistem keselamatan bersertifikat;
> jangan dipakai sebagai interlock mesin. Lihat [CHANGELOG.md](CHANGELOG.md) untuk riwayat.

## Arsitektur saat ini

```text
 Kamera SC3336 ──► Luckfox Pico Mini B ──RTSP lewat USB──► Laptop ("otak" AI)
   (dalam tabung,      (rkipc 10 fps,                       │  YOLO11n-pose  : orang + 17 titik tubuh
    diputar 90°)        profil ringan)                      │  PPE YOLOv8n   : helm, sepatu
                                                            │  warna hi-vis   : rompi (model belum punya kelas rompi)
                                                            │  MediaPipe      : gestur jempol / telapak terbuka
                                                            │  tracker + brain: lock, grup, pelanggar, patroli
                                                            ▼
                                     Arduino Uno R3 (USB, protokol SLP/1.1, 115200)
                                       servo pan D11 + tilt D7 (zona aman trapesium,
                                       gerak halus ease-in/ease-out, animasi angguk/geleng)
                                       LCD 16x2, LED helm/rompi/sepatu, sirine via relay+TPA3110,
                                       kipas MOSFET + DS18B20, monitor tegangan 5 V
```

Dashboard web live: **http://127.0.0.1:8080** (video beranotasi, status tiap orang, kontrol).

## Fitur utama

| Fitur | Keterangan |
|---|---|
| **Person-lock** | Orang pertama yang terlihat langsung dikunci dan diikuti walau sedang berjalan (prediksi gerak + kompensasi latensi). |
| **Gerak tenang & halus** | Kamera diam selama orang masih dalam ±6° dari tengah (geser 1–2 cm tidak membuat servo bergerak). Saat bergerak: profil trapesium + 2 tahap penghalus eksponensial = ease-in/ease-out tanpa patah-patah. |
| **Multi-orang** | 2+ orang: kamera membingkai semuanya; tiap orang dicek per bagian tubuh. |
| **Bagian tertutup = BELUM PASTI** | Visibilitas helm/badan/kaki ditentukan dari titik pose. Bagian yang tidak terlihat tidak pernah dianggap "tidak pakai". |
| **Prioritas pelanggar** | Pelanggar terkonfirmasi tetap dikunci walau ada orang lain masuk frame. |
| **Patroli** | Tiap 60 detik tanpa orang: kiri, kanan, kiri, kanan, kiri, lalu tengah, halus. Langsung berhenti begitu ada orang. |
| **Gestur** | Jempol → **angguk** (cooldown 5 detik) + salam. Jempol saat APD kurang → **geleng sekali** + "Mohon lengkapi APD". Telapak terbuka/melambai → **sapa** + suara. |
| **Suara** | Salam bahasa Indonesia (Halo, Hai, Selamat pagi/siang/sore/malam, Hati-hati ya) di speaker laptop. Speaker rig: nada lembut tanpa dengung, alarm minor C-Eb-G yang tenang + pengumuman "Mohon lengkapi APD". Volume default **50%** (slider di dashboard). |
| **Robot celingak-celinguk** | Saat target hilang: menengok ke arah jalannya, lalu melirik balik, sebelum kembali ke patroli. |
| **LCD tenang** | Teks normal berganti maksimal tiap 3 detik; alarm/putus link langsung menimpa. Teks LCD juga tampil di dashboard (preview 16x2). |
| **Kipas pintar** | Kipas Arduino dan kipas Pico dikendalikan MOSFET berdasarkan DS18B20 dan suhu SoC Pico. Tanpa sensor: kipas mati; DS18B20 yang dicolok belakangan langsung terdeteksi tanpa upload ulang. |
| **Kalibrasi kamera otomatis** | Tombol "Kalibrasi kamera": servo bergerak ±5°, sistem mengukur rotasi, kemiringan tabung dan FOV dari pergeseran gambar, lalu menyimpannya. Plus rotasi otomatis dari orang tegak. |
| **Zona aman servo** | Batas hasil ukur rig ini (lihat di bawah) dijaga di firmware **di setiap langkah 20 ms**, juga di tengah gerakan dan animasi. |

## Menjalankan (Windows)

```powershell
cd D:\RUDY\HAIKAL\APDChecker\python
..\.venv\Scripts\python.exe -m sentinel.app --camera luckfox --port COM6
# buka http://127.0.0.1:8080
```

Opsi penting:

| Flag | Arti |
|---|---|
| `--camera 0` | pakai webcam laptop (tes AI tanpa Pico) |
| `--port none` | tanpa Arduino (AI + dashboard saja) |
| `--mute` / `--sound` | matikan / nyalakan suara |
| `--volume 50` | volume 0..100 % |
| `--no-voice` | tanpa suara salam dari laptop |

Setelan rig ada di **`config/sentinel.json`** (rotasi kamera, arah servo, interval patroli,
suara, volume). Ubah di sana, bukan di kode.

### Instalasi baru

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install torch==2.14.1+cpu torchvision==0.29.1+cpu --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python.exe -m pip install -r python\requirements-host.txt
.venv\Scripts\python.exe -m pip install --no-deps mediapipe==1.1.1 ; .venv\Scripts\python.exe -m pip install absl-py flatbuffers
```

`platform-tools/` (adb) tidak ikut di repo: unduh *Android SDK Platform-Tools* dari Google dan
ekstrak ke `APDChecker/platform-tools/`.

## Firmware Arduino

Sketch: `arduino/apd_sentinel/` (v3.2, 31.182 / 32.256 byte flash).
Logika inti (`sentinel_core.c`) adalah C murni dan **diuji di PC dengan file yang sama persis**.

```powershell
.tools\arduino-cli-1.5.1\arduino-cli.exe compile --fqbn arduino:avr:uno --config-file .tools\arduino-cli-1.5.1\arduino-cli.yaml arduino\apd_sentinel
.tools\arduino-cli-1.5.1\arduino-cli.exe upload  --fqbn arduino:avr:uno -p COM6 --config-file .tools\arduino-cli-1.5.1\arduino-cli.yaml arduino\apd_sentinel
```

Library: `Servo` (bawaan). LCD (PCF8574, 0x27, A4/A5) dan DS18B20 ditulis langsung tanpa library.

### Pin Arduino

| Pin | Fungsi | Pin | Fungsi |
|---|---|---|---|
| D0/D1 | Serial (USB sekarang; UART Luckfox nanti) | D8 | LED alarm |
| D2 | DS18B20 Arduino | D9 | Audio → input TPA3110 |
| D3 | DS18B20 Pico | D10 | Relay daya TPA3110 |
| D4 | LED helm (merah) | D11 | Servo pan (kanan-kiri) |
| D5 | MOSFET kipas kamera+Pico | D12 | LED rompi (hijau) |
| D6 | MOSFET kipas Arduino | A0 | LED sepatu (kuning) |
| D7 | Servo tilt (naik-turun) | A4/A5 | LCD 16x2 I2C |

### Zona aman servo (diukur pemilik, 24-10-2026)

Sudut = angka `Servo.write()`. Pan: 0° = mentok kanan, 145° = mentok kiri, 90° = depan.
Tilt: 180° = lurus depan (paling atas), **kecuali saat menoleh kanan: maks 170°** di pan 0°
(naik lurus ke 180° di pan 90°). Batas bawah tilt ikut pan: 145° saat pan 0°, 100° saat
pan 145°. Firmware menjamin "angkat dulu, baru putar" di pojok bawah dan "turunkan dulu,
baru putar" ke pojok kanan atas. Ubah lewat console serial: `#CAL,1`, `#SET,T,MIN0,1450`, `#SET,T,MAXR,1700`, `#SAVE`, `#CAL,0`.

### Console serial (Serial Monitor 115200, newline)

`#HELP`, `#CAL,1`, `#JOG,P,900`, `#SET,P,MIN,0`, `#SAVE`, `#CAL,0`, `#VOL,50`,
`#FX,N` (angguk) / `#FX,H` (geleng) / `#FX,C` (celingak) / `#FX,W` (sapa), `#FAN,A,200`.

## Kabel Pico ↔ Arduino (untuk mode standalone nanti)

UART3 Pico: **pin 12 = TX → Arduino D0**, **pin 13 = RX ← Arduino D1 lewat pembagi 1 kΩ/2 kΩ**
(pin Pico 3,3 V), **pin 21 GND ↔ GND**. Jangan pakai UART2 (pin 4/5): itu console Linux.
Selama Arduino memakai USB, kabel ke D0 harus dilepas.

## Tes

```powershell
.venv\Scripts\python.exe scripts\test_apd_offline.py          # 320 tes (termasuk firmware native)
.venv\Scripts\python.exe -m unittest tests.test_sentinel -v    # 20 tes Sentinel v3.2 (+ skenario MCU simulasi)
.venv\Scripts\python.exe scripts\sentinel_hil.py --port COM6   # tes di rig asli (servo BERGERAK, alarm bunyi)
.venv\Scripts\python.exe scripts\sentinel_hil.py --sim         # skenario sama tanpa hardware
```

Tes native firmware memeriksa antara lain 2.400 gerakan acak yang tidak pernah keluar zona,
animasi di keempat pojok zona, pacing LCD, protokol SLP/1.0 dan 1.1, serta kehalusan output servo.

## Struktur folder

```text
APDChecker/
  arduino/apd_sentinel/   firmware Uno v3.1 (core C teruji + sketch)
  arduino/legacy/         firmware lama v2.2 dan kandidat APD3 (arsip)
  python/sentinel/        otak AI: app, vision, tracker, brain, gesture, interact, voice, link
  python/apd_runtime/     modul lama (offline policy, thermal audit, dsb.)
  config/sentinel.json    setelan rig
  docs/sentinel/          kontrak protokol SLP/1.1
  docs/luckfox/           catatan Luckfox (thermal, NPU, USB) + bukti debug
  edge/luckfox/           skrip guard kamera on-board + profil rkipc ringan
  assets/voice/           suara salam (edge-tts, id-ID-GadisNeural)
  models/                 yolo11n-pose, ppe_yolov8n, yolov8n, gesture_recognizer
  hardware/               CAD (STEP, Blender) dan gambar rangkaian
  tests/                  tes Python + tes native firmware
```

## Keterbatasan yang jujur

* AI berjalan **di laptop**. Pico saat ini menjadi kamera. Standalone penuh di NPU Pico
  butuh model RKNN (konversi di Linux) dan program C; lihat `docs/luckfox/RV1103_BACKEND.md`.
* Model APD lama **tidak punya kelas rompi**. Rompi dan helm (cadangan) dideteksi lewat warna;
  ditandai `COLOR` di dashboard. Dataset sendiri + training ulang akan jauh lebih akurat.
* **Daya servo**: saat servo bergerak, 5 V Arduino turun ke ±4,3 V (terukur 27-10-2026) dan
  USB sesekali tersendat. Software sudah tahan (tanpa reset), tapi servo sebaiknya punya
  step-down sendiri 5–6 V ≥ 3 A dengan GND disatukan ke Arduino.
* **Pico hilang dari USB** beberapa menit setelah kamera menyala (berulang). Dugaan: daya /
  kabel USB. Aplikasi menunggu dan menyalakan kamera lagi begitu Pico muncul.
