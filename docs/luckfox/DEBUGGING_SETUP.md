# Setup debugging kamera dan AI APDChecker

Diperbarui 11 Oktober 2026. Rencana "Sabtu depan": **17 Oktober 2026, WIB**.
Ini rencana pengujian, bukan janji semua tes lulus pada tanggal itu.

## 1. Status yang benar saat ini

- **Relay/TPA3110/speaker sudah berfungsi menurut pengujian operator.** Source
  `arduino/apd_receiver/apd_receiver.ino` diperiksa: relay D10, tone D9, LED alarm
  D8, servo D11, serial 9600. Firmware yang benar-benar terpasang tetap perlu
  dicocokkan sebelum integrasi serial; tidak ada upload atau tes hardware baru
  pada penyusunan dokumen ini. Sketch working tersebut tidak diubah.
- Sketch legacy otomatis patroli setelah 60 s. Uji akurasi harus memakai kamera
  tetap: putus sambungan servo ketika sistem tidak mendapat daya, lalu amankan
  kamera di dudukan. Jangan mengirim perintah serial untuk "membekukan" kamera.
- **Catatan pembacaan kode:** array nada menulis 180 ms bunyi / 820 ms hening,
  tetapi loop menaikkan index setelah memainkan nada, kemudian menunggu durasi
  index berikutnya. Saat berulang, nada 750 Hz ditahan sekitar 820 ms dan hening
  sekitar 180 ms. Bukan klaim hasil osiloskop; verifikasi pola yang memang kamu
  inginkan saat commissioning. Ini tidak membatalkan laporan bahwa suara bekerja.
- Kandidat APD3 adalah firmware berbeda: belum di-upload/commissioning. Gate
  OFF pada config/kandidat tidak berarti relay legacy secara fisik sedang OFF.
  **Jangan kirim frame APD2/APD3 ke parser legacy:** karakter di frame dapat
  memicu relay/servo. Tidak membuka COM Uno pada tahap kamera/AI-only.
- Logika cache/UNKNOWN/removal/re-wear/fault sudah memiliki tes HOST sintetis.
  Tes itu tidak membuktikan kamera mengenali APD di lapangan.
- Static preflight checkpoint PPE sekarang memuat helmet/shoes dan negatives,
  tetapi **tidak vest/no_vest/person**. Person dari model umum bukan PPE fallback.
- Backend kamera RV1103 + RKNN model APD asli belum terintegrasi/tervalidasi;
  decoder kandidat tidak boleh dianggap mendukung sembarang tensor YOLOv8.
  Lihat `RV1103_BACKEND.md`, `RKNN_ENGINE_CANDIDATE.md` dan `GRID_DECODER.md`.

## 2. Yang perlu kamu siapkan sebelum memberi sinyal "siap tes"

### Paket A -- koneksi dan kamera saja, tanpa Arduino

- [ ] PC/laptop dengan folder project dan kabel **USB data** Pico yang baik.
- [ ] Pico Mini B dan SC3336 sudah terpasang; pemasangan/penggantian ribbon
  hanya ketika seluruh daya dilepas. Tidak membongkar kabel ketika menyala.
- [ ] Kamera di dudukan tetap, posisi tidak bergeser, orang bisa terlihat dari
  kepala hingga kedua kaki. Tandai area lintasan dan catat jarak nyata.
- [ ] Pendinginan terbuka yang kamu punya; catat heatsink/kipas yang benar-benar
  terpasang. Jangan memasukkan ke tabung dahulu untuk tes ini.
- [ ] Operator berada di lokasi untuk stop/power-off jika komunikasi/guard gagal.
- [ ] Uno tidak tersambung ke tool serial; servo diamankan/dilepas saat power-off.
  Amplifier tidak perlu dinyalakan untuk uji kamera/akurasi di PC.

Pico diberi daya dari jalur board yang sesuai, bukan Uno GPIO/pin 3.3 V.
USB PC masing-masing board dapat dipakai untuk tahap terpisah; jangan menambah
jalur suplai antar-board yang belum ditinjau. Review daya penuh tetap ditunda.

### Paket B -- uji APD asli, sesudah model/backend siap

- [ ] Satu peserta bersedia; dua peserta untuk tes berpapasan. Pakai tag anonim
  A/B untuk pencatatan, bukan face recognition atau identitas biometrik.
- [ ] Helm, rompi dan sepatu yang benar-benar digunakan di bengkel.
- [ ] Tentukan "sepatu": semua alas kaki tertutup, atau kategori safety shoes?
  Pengamatan visual tidak membuktikan sertifikasi perlindungan sepatu.
- [ ] Area uji terisolasi aman: **jangan melepas APD di area bahaya bengkel aktif**.
  Kasus tanpa sepatu dapat disiapkan lewat klip berizin/area aman; bukan berjalan
  tanpa perlindungan di bengkel. Pastikan persetujuan sebelum menyimpan klip.
- [ ] Kondisi terang/redup, dekat/jauh, berjalan normal/cepat sesuai jalur nyata.
- [ ] Anotator manusia mencatat keadaan APD dan visibilitas **sebelum melihat
  prediksi model**. AI tidak boleh memberikan label kebenaran untuk dirinya sendiri.

Untuk tes real-time penuh: butuh Paket A + B + checkpoint berlisensi dengan
kelas sesuai + `.rknn` kompatibel runtime + adapter frame/visibility/inferensi
nyata. Jika belum siap, kita tetap bisa menguji preview, mengumpulkan data
berizin dan replay logika, **bukan menyebutnya uji akurasi APD Pico**.

## 3. Matriks pekerjaan -- kamu setup, assistant otomasi

| Tes | Kamu siapkan | Otomasi yang sudah tersedia / perlu dibuat | Status |
|---|---|---|---|
| Unit/replay logika | PC + project | Suite Python/C, cache/TTL/UNKNOWN/removal/fault | READY_HOST |
| Pico terhubung | Pico + USB data | Discover ADB, identifikasi board/serial, snapshot read-only | NEED_SETUP |
| Kamera hidup + stream | SC3336, fixed mount, cooling, operator | Guard start/stop bounded; delivery frame/FPS, suhu/CPU/RAM | NEED_SETUP; camera-only |
| Framing/orientasi | Peserta terlihat seluruh tubuh, jarak | Preview PC; operator konfirmasi orientasi/framing | NEED_SETUP; bukan inference |
| Akurasi item nyata | Paket A+B, label manusia | Inference + matching ground truth + score; backend belum siap | BLOCKED_MODEL_BACKEND |
| Cache/dua orang/removal nyata | Skenario D05-D10 + model/backend | Catat track, fresh/cached/TTL/UNKNOWN, delay dan ID switch | BLOCKED_MODEL_BACKEND |
| Fault kamera/model | Operator, pipeline tervalidasi | Replay fault HOST sekarang; disconnect stream software live nanti | READY_HOST / LIVE_PENDING |
| Integrasi indikator/alarm | Uno, firmware/protokol cocok, wiring dikonfirmasi | Session/ACK/timeout dan output terkontrol; legacy audio sudah bekerja | NEED_COMMISSIONING |
| Dua servo | Servo baru, supply, bracket | Limit/home/settle/pin mapping dan motor protocol | DEFERRED |
| Daya/UPS/tabung/fan | Fan terpasang, enclosure dan alat ukur | Rail/peak current/brownout/soak; bukan sekadar suhu chip | DEFERRED |

Tidak ada otomasi yang dapat mengetahui ground truth, membuktikan posisi
mekanis atau mendengar speaker hanya dari ACK/log. Bagian tersebut membutuhkan
konfirmasi manusia atau sensor/alat ukur yang tepat.

## 4. Urutan sesi langsung

1. **Preflight HOST:** jalankan suite, cek file/versi, jangan mulai kamera.
2. **Discovery:** baca ADB devices, cocokkan board Mini B, catat serial aktual.
   Jangan menebak serial dari label "Nexus"/nama Windows atau serial lama.
3. **Baseline singkat:** snapshot idle read-only; periksa suhu valid, uptime,
   free memory, proses kamera, hash guard dan status lock. Jangan takeover sesi
   kamera lain atau menghapus lock tanpa investigasi.
4. **Kamera saja:** mulai 60 s supervised dengan default cutoff 60 C; verifikasi
   fresh delivery/orientasi, stop dan konfirmasi CAMERA_IDLE. Perpanjang bertahap
   sampai 300 s hanya setelah hasil diperiksa. 78 C tetap **batas stop maksimum
   yang kamu minta**, bukan target kerja atau jaminan suhu tidak overshoot.
   Audit read-only hanya mencatat/exit; bukan perintah shutdown. Guard workload
   berbeda dan harus diverifikasi masih terpasang. Jangan auto-restart saat fault.
5. **Readiness model:** verifikasi classes/hash/licensing, input/output,
   INT8 parity/SDK ABI dan frame freshness. Jika gagal, sesi akurasi ditandai
   BLOCKED, bukan mengganti kelas mask menjadi vest atau memalsukan hasil.
6. **APD di PC-first:** outputs OFF, model nyata menjalankan skenario D01-D10.
   Camera preview terpisah dari inference; simpan latency/gap/temperature bersama
   laporan tiap orang. Tidak mengirim command Uno pada tahap ini.
7. **Review:** cocokkan anotasi manusia, hitung hasil, periksa failures sebelum
   tuning. Pakai klip/orang lain sebagai holdout setelah tuning threshold.
8. **MCU kemudian:** identifikasi firmware dan protokol, migrasi terpisah jika
   diperlukan, pertahankan relay/audio accepted. Tes output diawasi dengan stop
   plan dan volume wajar; bukan mengaktifkan alarm tiap frame.

Mulai fixed-camera, target sampling inferensi 3 FPS diuji, bukan diasumsikan
cukup. Bandingkan 5 FPS jika kasus melintas hilang/terlambat; log FPS capture,
inference dan preview secara terpisah. Sensor masih bisa bekerja pada FPS lain
meskipun inferensi diminta 3 FPS. Jangan menganggap mengurangi tampilan PC sama
artinya menurunkan beban sensor/NPU.

## 5. Skenario lapangan

Manifest: `config/debug_scenarios.json`. Semua awalnya NOT_RUN.
Usulan 10 pengulangan/skenario hanya baseline debugging, bukan ukuran sampel
sertifikasi atau bukti probabilitas false alarm yang cukup.

| ID | Setup | Hasil yang diperiksa |
|---|---|---|
| D01 | Helm+rompi+sepatu; diam lalu berjalan | Item benar; tidak alarm APD |
| D02 | Tanpa helm, kepala jelas | ABSENT helm setelah bukti/debounce |
| D03 | Tanpa rompi, torso jelas | ABSENT rompi setelah bukti/debounce |
| D04 | Tanpa sepatu, kaki jelas, area aman | ABSENT sepatu sesuai definisi |
| D05 | Kaki belum masuk frame/tertutup | UNKNOWN; cache valid hanya sampai TTL |
| D06 | Kepala/torso tertutup bergantian | Tidak menafsirkan tidak terlihat sebagai tidak memakai |
| D07 | Lepas, lalu pakai lagi satu item in-frame | Cache dibatalkan oleh bukti fresh; ukur kedua delay |
| D08 | Dua orang berpapasan, kelengkapan berbeda | Tidak mencampur item; ambiguitas dan ID switch dicatat |
| D09 | Masuk/keluar/kembali, dekat/jauh | TTL benar; re-entry bukan janji orang lama dikenali |
| D10 | Cepat, redup/backlight | Missed person/item dan waktu reaksi, bukan hanya gambar bagus |
| D11 | Frame kosong, lalu hentikan stream software | NO_PERSON dibedakan dari CAMERA_FAULT |
| D12 | Timestamp stale, gap, model error di replay | Fault/UNKNOWN; tidak mempertahankan SAFE lama |

Ambil beberapa sudut/kecepatan yang sama dengan pemasangan akhir. Jika kaki tidak
muat, benahi posisi/framing dahulu; jangan memaksa status lengkap dari cache tanpa
batas. Pengujian pan/tilt dan lintas-view fisik menunggu kalibrasi dua servo.

## 6. Bukti dan cara mengukur (tidak hanya "akurasi 95%")

Salin template ke folder sesi baru, jangan isi template induk dengan hasil uji:
- `debug/templates/session_manifest.example.json`: identitas sesi, cooling,
  firmware/backend/model hash, kelas, definisi sepatu, status output dan consent.
- `debug/templates/accuracy_observations.csv`: satu row/item/orang/observation.
  ID observation mengikuti anotasi manusia, bukan hanya orang yang ditemukan AI.
  Jika model melewatkan orang, tetap buat row dengan prediction UNKNOWN,
  evidence_mode NONE, unknown_reason DETECTOR_MISSED_PERSON, matched_track kosong.

Kolom penting:
- item: vest/shoes/helmet.
- ground_truth: PRESENT/ABSENT jika region jelas; UNOBSERVABLE jika tak bisa
  dinilai dari gambar. Label manusia independen; jangan pakai prediksi model.
- prediction: PRESENT/ABSENT/UNKNOWN; evidence_mode FRESH/CACHED/NONE.
- UNKNOWN wajib punya reason. Known wajib punya evidence. Track ID bisa kosong
  untuk missed person; participant_tag hanya tag pengujian anonim.
- capture_ms/decision_ms: pasangan waktu **monotonik dalam domain yang sama**,
  bukan mencampur clock PC/Pico. Boleh kosong jika belum ada timestamp sah.

`score_apd_accuracy.py` mengolah CSV **tanpa perangkat**, menghitung confusion
matrix per item, visible false alarms, false SAFE, abstentions, coverage dan
capture-to-decision latency. Recall pelanggaran memasukkan ABSENT->UNKNOWN ke
penyebut sehingga AI yang selalu UNKNOWN tidak mendapatkan recall sempurna.
Precision diberi label **observable-only**; periksa false assertion fresh pada
region UNOBSERVABLE terpisah. Cached known pada UNOBSERVABLE belum tentu salah:
review TTL, epoch dan bukti sebelumnya. Script tidak menilai keabsahan cache itu.

Hitungan ini per-observation, bukan mAP bounding box, false alarm per jam/100
orang, ID switch, confidence interval atau delay sejak APD dilepas. Untuk itu
masih butuh adapter evaluator/log event dan anotasi waktunya; jangan menyatakan
fitur evaluator itu sudah tersedia. Repeated frames satu peserta berkorelasi.
Uji PC float vs INT8 Pico pada holdout yang sama ketika model siap; kelulusan
float tidak membuktikan kelulusan RKNN INT8. Ambang acceptance belum disepakati.

Catat pula: boxes orang/item, label/confidence, visibility reason, track ID,
fresh/cached/age/TTL, decision/fault, model hash, capture/inference timestamps,
FPS/gap, CPU/RAM/CMA dan suhu. Simpan angka/log di PC; gambar hanya atas izin
untuk anotasi. Hindari continuous recording/flash writes di Pico untuk debug ini.

## 7. Perintah yang benar-benar ada (jalankan dari root project)

Root sekarang: `D:\RUDY\HAIKAL\APDChecker`. Setelah migrasi gunakan root aktual.
**HOST saja, aman dari akses kamera/serial:**

```powershell
& .\.venv\Scripts\python.exe scripts/test_apd_offline.py
& .\.venv\Scripts\python.exe scripts/check_native_core.py --zig .tools/ziglang-0.13.0/ziglang/zig.exe --workshop
& .\.venv\Scripts\python.exe scripts/debug_apd_computer.py --demo --duration 60
```

Demo memakai data sintetis; status AI/OUTPUTS OFF. Bukan model yang sedang melihat
orang. Untuk menilai CSV sesi **berisi hasil nyata**, jangan pakai template kosong:

```powershell
& .\.venv\Scripts\python.exe scripts/score_apd_accuracy.py --observations 'PATH_SESI\observations.csv' --output 'PATH_SESI\accuracy-report.json'
```

Output harus baru (script menolak menimpa laporan lama); CSV kosong ditolak,
bukan dilaporkan sebagai 100% akurat.

**Live setelah operator siap -- bukan perintah yang dijalankan sekarang:**

```powershell
& .\platform-tools\adb.exe devices -l
# Ganti SERIAL_TERVERIFIKASI setelah cocokkan board, bukan copy serial lama:
& .\.venv\Scripts\python.exe scripts/control_luckfox_preview.py status --serial SERIAL_TERVERIFIKASI
& .\.venv\Scripts\python.exe scripts/test_luckfox_camera_supervised.py --serial SERIAL_TERVERIFIKASI --duration 60 --cutoff-c 60 --operator-supervised --view-stream
```

Script camera test menyimpan metrics/stream delivery, tidak menyimpan gambar,
tidak membuka Uno dan **tidak melakukan inferensi APD**. Ia menggunakan guard
yang sudah terpasang; jika guard hilang setelah reset/migrasi, investigate dahulu,
bukan lanjut blind-start. Forward port 18554 tidak boleh sedang dipakai sesi lain.
Dashboard RTSP hanya membaca stream yang sudah aktif; tidak otomatis menyalakan
kamera. Jangan membuka reader kedua jika mengganggu pengukuran delivery FPS.
Vendor NPU test hanya smoke test vendor, bukan evaluator model APD kita.

## 8. Batas sesi Sabtu dan pekerjaan ditunda

**Ditunda sesuai permintaan:** kalibrasi dua servo; uji catu/peak current/UPS/
brownout; uji kipas/tabung enclosure dan thermal soak pemasangan final. Tidak ada
rencana mencabut ribbon hidup, memaksa brownout atau stress tanpa batas.

Saat kamu siap, kirim: **"Pico terhubung, kamera fixed, cooling [yang terpasang],
Uno/servo tidak ikut tes; siap camera-only."** Aku dapat menjalankan discovery
kemudian tes kamera terukur. Untuk akurasi lengkap, readiness model/backend harus
lulus dahulu; kalau belum, hasil yang jujur adalah kamera/data siap, AI blocked.
Tidak ada monitor berjalan di background dari dokumen ini.
