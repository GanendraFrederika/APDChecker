# Checklist APDChecker menuju uji bengkel dan produksi

Diperbarui: 11 Oktober 2026. Status: **prototipe; deployment/gate kandidat OFF**.
Sketch legacy relay/audio telah diuji bekerja oleh operator; status gate kandidat
bukan pembacaan keadaan fisik relay saat ini. Panduan setup: `DEBUGGING_SETUP.md`.
Checklist ini bukan bukti kelulusan produksi. `[x]` menyebut cakupan bukti;
`[ ]` berarti pekerjaan belum selesai atau belum diuji pada hardware nyata.

## Tujuan dan pembagian tanggung jawab

- Luckfox Pico Mini B + SC3336: kamera, inferensi NPU, asosiasi orang/APD,
  cache berumur pendek, alasan UNKNOWN, kesehatan sistem, komunikasi MCU.
- Uno: indikator dan aktuator deterministik, timeout/ACK/watchdog; nanti pan/tilt.
- Daya: subsystem terpisah; UPS ditunda, bukan diasumsikan sudah aman/selesai.
- Rompi -> hijau, sepatu -> kuning, helm -> merah. Tiga lampu menyala hanya
  setelah APD orang yang dipilih terkonfirmasi lengkap.
- Bagian tubuh tersembunyi/belum terlihat -> UNKNOWN, bukan pelanggaran.
- Jangan gabungkan helm orang A + rompi orang B + sepatu orang C.
- Fungsi awal: pemantauan/peringatan. Bukan interlock mesin berperingkat keselamatan.

## 1. Bukti software yang sudah ada (HOST, bukan deployment)

- [x] Pemetaan APD/warna dan konfigurasi aktuator OFF.
- [x] Tracking geometrik sementara, TTL cache, sampel/waktu konfirmasi,
  pemisahan orang, penanganan silang/ambigu dan fault. Bukan face recognition/re-ID.
- [x] Logika melepas/memakai ulang APD: bukti berlawanan membatalkan kesimpulan lama.
- [x] Missing detection tidak otomatis menjadi ABSENT; negatif perlu visibility tervalidasi.
- [x] Kontrak framed APD3 + CRC/session/sequence/ACK/timeout diuji di HOST.
- [x] Kandidat receiver Uno terpisah dari sketch legacy; alarm default OFF.
- [x] Dashboard debug memisahkan SIMULASI dari preview kamera asli.
- [x] Guard preview pengembangan dibatasi waktu/sensor/USB; pengujian sebelumnya
  bukan bukti suhu saat model PPE kita berjalan. Tidak mengubah batas ini menjadi
  klaim chip pasti aman atau suhu tidak bisa overshoot.
- [x] Baru: metadata view epoch + moving/settling menghapus cache Python/C.
  Frame buffered dari view lama ditolak. Invalidasi tersedia di antara frame.
- [x] Baru: coordinator pan/tilt HOST tanpa I/O: move -> ACK -> settle -> reacquire,
  timeout/stale ACK fail-closed. BUKAN driver servo atau protokol motor siap pakai.

Bukti Python terbaru: `debug/offline-tests-20261011-debug-plan.log` (243 tes;
termasuk 14 tes scorer sintetis, bukan akurasi model). Bukti camera-view sebelumnya:
`debug/offline-tests-20261011-camera-view.log` (229 tes),
`debug/native-tests-20261011-camera-view.log` (C/Python parity 614 frame sintetis,
1024 box transform, 263 stream MCU, 256 tensor decoder; seluruh suite HOST lulus).
Tidak ada koneksi hardware atau upload firmware pada pekerjaan ini.

## 2. Prioritas P0 -- agar benar-benar ada AI APD di Pico

Urutan ini lebih penting daripada menambahkan fitur motor/UPS sekarang.

- [ ] Tetapkan definisi sepatu: sepatu biasa atau safety shoes tertentu? Kamera
  tidak otomatis membuktikan sertifikasi/perlindungan sepatu dari tampilannya.
- [ ] Siapkan model/data berlisensi untuk person + vest/no_vest + shoes/no_shoes +
  helmet/no_helmet, atau desain ulang kontrak model secara eksplisit. Checkpoint
  sekarang tidak memiliki vest/no_vest/person; jangan mengubah mask menjadi vest.
- [ ] Pisahkan data train, calibration INT8, dan evaluasi orang/klip lapangan.
- [ ] Labeled cases: berjalan, kecil/jauh, kaki terpotong, tertutup orang lain,
  dua orang berpapasan, APD dilepas/dipakai, glare dan cahaya bengkel.
- [ ] Validasi body visibility/occlusion; box di gambar saja bukan bukti OBSERVABLE.
- [ ] Cocokkan SDK/header/API dan ABI dengan runtime RV1103/uClibc terpasang;
  jangan mengganti .so atau OS tanpa backup/rencana rollback.
- [ ] Model .rknn nyata, label/output/tensor/quantization/hash tervalidasi.
  Decoder kandidat sekarang mendukung YOLOv5 post-sigmoid INT8 NCHW 3-head,
  bukan sembarang output YOLOv8 atau layout native lain.
- [ ] Integrasi frame RK-MPI -> preprocessing upright -> RKNN -> inverse letterbox
  -> visibility -> tracker -> laporan, dengan timestamp capture monotonik.
- [ ] Ukur latency/FPS end-to-end, gap, RAM/CMA, buffer leaks, CPU/NPU dan suhu.
  FPS kamera/vendor NPU bukan FPS maupun akurasi model PPE kita.
- [ ] Mulai kamera FIXED; target 3 FPS hanyalah proposal, terima berdasarkan waktu
  melintas dan bukti deteksi. Orang lewat singkat mungkin butuh kebijakan berbeda.

## 3. Bahan saat ini dan batas pengujian

Inventaris berdasarkan laporan operator, belum diverifikasi model/rating fisiknya.

| Bahan | Bisa direncanakan sekarang | Yang masih menghalangi penyambungan |
|---|---|---|
| Pico Mini B + SC3336 | Pipeline, debug, kamera fixed | Supply sehat, heatsink/enclosure dan uji model asli |
| Uno | Receiver/simulasi; commissioning terpisah | Wiring/bootloader/polaritas belum diterima; belum upload kandidat |
| Relay 1 channel + TPA3110 + speaker | Legacy D10 relay + D9 tone: operator sudah membuktikan berfungsi | Integrasi pipeline baru, timeout/fault, rating/interface dan uji daya belum diterima |
| 1 servo; 2 servo baru sedang dibeli | Reservation pin dan motion gate | Model/range/stall current, catu motor, bracket dan limit |
| 3x18650 + holder + BMS FL25A-A | Inventaris kebutuhan backup | Charger CC/CV, balancing/proteksi yang diverifikasi, fuse, power-path |
| Meter digital 5 kabel | Rencana monitoring rail | Model/skema shunt dan rail power belum diketahui |
| Saklar + jack DC 3 kaki | Layout/case | Rating saklar, terminal switched dan polaritas belum diukur |
| Strip breadboard | Debug low-current sementara | Bukan distribusi produksi amplifier/motor/baterai |
| LED/resistor terpakai | Pin plan | Tidak boleh diasumsikan ada resistor/pull-up/proteksi cadangan |

Jangan merangkai semua ready parts sekaligus. Ketersediaan BMS bukan bukti ada
charger/UPS/regulator. Jangan langsung paralel adaptor dan baterai, atau gunakan
resistor sebagai charger permanen. Meter/shunt tidak boleh mem-bypass jalur BMS.

### Batas daya/sinyal sebelum commissioning

- [ ] Pico memakai supply USB/VBUS yang sesuai, bukan Uno GPIO atau pin 3.3 V.
- [ ] Catu servo terpisah yang sesuai tegangan dan peak/stall current kedua motor;
  bukan regulator Uno. Review referensi GND dan arus balik agar noise tidak lewat kamera.
- [ ] Antarmuka Uno 5 V -> Pico 3.3 V dilindungi/level-shift, termasuk risiko back-power.
- [ ] Tidak ada bare relay coil yang langsung digerakkan GPIO; verifikasi modul driver
  dan proteksi coil yang benar, bukan menebak dari jumlah channel.
- [ ] Speaker pada pasangan output amplifier yang sesuai; output BTL minus bukan
  GND catu. Jangan langsung beri input audio TPA dari tone/GPIO tanpa conditioning.
- [ ] Fuse, terminal, kabel, strain relief, polaritas dan rating beban diterima.
- [ ] Sel 18650 chemistry/keadaan/matching dan holder aman; charger sesuai 3S.

Catatan audio: sketch legacy sudah menghasilkan tone D9 dan mengendalikan relay
D10; operator melaporkan speaker berfungsi. Tidak perlu merancang ulang fungsi
basic itu. Kandidat APD3 terpisah belum di-upload/diuji dengan rangkaian ini;
perilaku pola nada, timeout dan interface listrik perlu diterima sebelum migrasi.
Tidak membutuhkan relay kedua hanya untuk dua servo.

## 4. Dua servo (P1, setelah fixed-camera bekerja)

Rancangan lengkap ada di `PAN_TILT_PLAN.md`.

- [ ] Tentukan model servo dan mekanisme: servo posisi, bukan continuous-rotation
  yang diasumsikan memiliki posisi sudut absolut.
- [ ] Pan/tilt memakai Uno; kandidat reservation D7/D8, BELUM aktif di firmware.
  Legacy saat ini memakai D8 untuk LED alarm dan D11 untuk servo: D8 bukan pin
  kosong. Review benturan pin, UART, library timer, tone/PWM dan versi core.
- [ ] Kalibrasi home, batas mekanik, limit pulsa/sudut, kecepatan, dwell dan deadband.
  Jangan langsung sweep 0..180 derajat atau home otomatis saat boot.
- [ ] Satu motor diuji tanpa beban, lalu bracket, lalu dua motor dengan beban aktual.
- [ ] ACK gerak bukan sensor posisi; tetapkan strategi feedback atau commissioning
  open-loop plus deteksi blur/fault. Jangan klaim bisa mendeteksi semua stall.
- [ ] Tambah protokol motor bounded/CRC/session/ACK/timeout, uji HOST dan AVR,
  kemudian upload terpisah dengan beban amplifier dilepas.
- [ ] Stamp epoch/stability pada exposure; buang frame yang melintasi perubahan view.
- [ ] Kamera bergerak/settle -> APD tidak dievaluasi, tidak bunyi alarm APD.
- [ ] Sesudah bergerak -> ID sementara dan bukti APD baru; tidak gabungkan cache
  kepala/kaki antar-sudut sebelum ada asosiasi lintas-view yang tervalidasi.

## 5. Commissioning MCU dan audio (P1)

- [x] **Laporan operator:** relay + TPA3110 + speaker bekerja pada sketch legacy.
  Source diperiksa: D10 relay, D9 tone, D8 LED alarm, D11 servo; bukan verifikasi
  live hardware oleh assistant. Tes berikut adalah integrasi baru/fault, bukan
  klaim audio dasar belum dibangun.

- [ ] Jangan kirim APD2/APD3 ke sketch legacy parser satu karakter: angka dalam
  frame bisa memicu aktuator. Identifikasi dan upload receiver kandidat terpisah.
- [ ] Verifikasi pin fisik: D4 hijau/vest, D5 kuning/shoes, D6 merah/helmet,
  D13 fault, D10 relay, D9 kandidat audio; wiring belum diotorisasi untuk energize.
- [ ] Pola UNKNOWN, pemilihan target saat banyak orang dan fault ditandatangani operator.
- [ ] Uji LED saja, lalu timeout/unplug/reset/noise serial, watchdog/bootloader.
- [ ] Uji relay tanpa amplifier, polaritas OFF saat boot/reset/disconnect.
- [ ] Uji audio/amp supply, gain, volume, durasi/cooldown; jangan spam per frame.
- [ ] Gate indikator dan alarm tetap OFF sampai masing-masing diterima.

## 6. Kreativitas yang layak dicoba -- usulan, belum fitur produksi

1. **Zona inspeksi fixed**: garis/area kamera tempat seluruh tubuh terlihat.
   UNKNOWN kaki -> alasan debugging "kaki belum terlihat", bukan teriakan.
2. **Explainable monitor**: tampilkan fresh/cached, umur bukti, track sementara,
   kamera stabil/bergerak, model version, suhu dan alasan fault.
3. **Event ledger bounded**: catat perubahan status (bukan gambar terus-menerus),
   rotasi log, hindari disk penuh/penulisan flash berulang. Privasi tanpa face ID.
4. **Gerak seperlunya**: home/fixed sebagai default. Pan/tilt sebagai operator
   setup/manual inspection terlebih dahulu, bukan chasing setiap pejalan kaki.
5. **PC preview on demand**: stream ringan hanya saat debug; inference dan preview
   punya telemetry berbeda. Tidak menjadikan gambar kamera bukti AI bekerja.
6. **Peringatan ramah**: kandidat kalimat spesifik setelah bukti fresh terkonfirmasi,
   cooldown; fault kamera/model beda dengan pelanggaran APD. Bunyi alarm legacy
   sudah bekerja; kalimat rekaman/TTS spesifik belum tersedia.

## 7. Release gates (P2) -- harus semuanya lulus sebelum production-ready

- [ ] Akurasi per item/visibility dan false alarm/missed violation pada holdout bengkel.
- [ ] Timing orang melintas; pembuktian debounce tidak terlambat/kehilangan kasus.
- [ ] Orang crossing, occlusion, removal/re-wear, kamera bergerak, buffered stale frames.
- [ ] Unplug kamera/USB/MCU, model error, reboot, serial corruption dan brownout.
- [ ] Uji supply, motor stall/fault, audio peak, boot OFF dan enclosure soak terukur.
- [ ] Heatsink/fan terpasang, sensor valid; 78 C adalah batas penghentian pengembangan
  yang diminta operator, bukan target, rating keselamatan chip atau jaminan ceiling.
- [ ] UPS/charger/fuse/power-path (tugas terpisah) baru dinilai saat komponen tersedia.
- [ ] Runbook pasang/stop/rollback, version hashes, backup dan acceptance operator.

## Cara menjalankan tes tanpa perangkat

Dari root project (gunakan path root yang benar setelah migrasi):

```powershell
& .\.venv\Scripts\python.exe scripts/test_apd_offline.py
& .\.venv\Scripts\python.exe scripts/check_native_core.py --zig .tools/ziglang-0.13.0/ziglang/zig.exe --workshop
```

Jangan menjalankan test legacy secara glob dari folder `python`; sebagian
mengakses serial/kamera. Dua perintah di atas memang untuk tes HOST terisolasi.

Referensi desain: Arduino "Servo Motor Basics" (catu eksternal sesuai motor),
Arduino UNO Rev3 pinout (batas pin 3.3 V), TI TPA3110D2 datasheet/product (analog
input dan BTL). Rating modul clone/servo/meter konkret tetap harus diverifikasi.
