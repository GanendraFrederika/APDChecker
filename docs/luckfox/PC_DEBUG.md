> Latest 11 October: operator confirms physical USB reconnect; 300 s guarded
> camera/RTSP passed, shipped vendor NPU activity observed separately. Neither
> is PPE inference. Use supervised HOST tools, NOT historical exec-out commands:
> ancient vendor adbd supports PTY shell only. Default cutoff60 / explicit <=78 C
> development test parameter. PRODUCTION_PROGRESS.md / VENDOR_NPU_TEST.md.
> Sections below retain historical setup state, not current deployment claims.

# Debug APD ke komputer â€” tanpa Arduino

10 Oktober 2026. Tiga mode terpisah. Ini bukan aplikasi AI produksi di Pico.

## Kondisi saat dibuat

- Logika Python person/item-cache dan transisi pasang/lepas diuji sintetis di host.
- Model PPE lokal tidak punya vest/no_vest. Adapter visibility tubuh, backend
  RK-MPI/RKNN dan tracker native belum dibuat. Tidak ada model RKNN/binary AI
  produksi yang bisa langsung di-upload ke Pico pada tahap ini.
- OpenCV 4.14.0.94 terpasang hanya di venv Windows. Import dan dukungan FFmpeg
  host diperiksa. Ultralytics belum terpasang. Demo tidak memerlukan keduanya.
- Probe shell sumber sudah tersedia, tetapi BELUM di-upload/dijalankan di Pico.
- Pada sesi pembuatan ini tidak ada ADB, akses board, kamera, UART, GPIO, Arduino,
  relay atau sirene. Karena board sebelumnya sangat panas, live masih menunggu
  pemeriksaan penyebab, kondisi power, konektor dan rencana pendinginan yang aman.

## 1. Demo OFFLINE: boleh dijalankan dengan Pico dan Arduino dicabut

~~~powershell
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\debug_apd_computer.py' --demo --duration 60
~~~

Buka http://127.0.0.1:8765 di browser komputer. Server hanya bind loopback.
JSON di /api/status. Ctrl+C berhenti lebih cepat. Durasi wajib 1..300 detik.
Tidak ada endpoint kontrol/actuator dan tidak ada dependensi serial.

Demo mengulang urutan sintetis 45 frame: APD lengkap, melepas/memasang kembali
rompi, sepatu, helm dengan track yang sama, kaki tertutup sampai cache habis,
lalu orang keluar. Pergantian siklus adalah reset simulasi, bukan identitas
permanen. Tidak menampilkan kamera, bounding box video, atau mengklaim hasil AI.

Tiga indikator virtual: true=PRESENT, false=ABSENT, null=UNKNOWN. Warna item:
rompi hijau, sepatu kuning, helm merah. Ketiganya dapat menyala sekaligus.

### Aturan perubahan APD yang sudah diuji

1. PRESENT + bukti no_item yang observable -> UNKNOWN segera; cache lama gugur.
2. Bukti negatif berlanjut >=1.5 s dan >=3 sampel frame baru -> ABSENT.
3. ABSENT + bukti item positif -> UNKNOWN segera; alarm candidate tidak dilanjutkan.
4. Bukti positif berlanjut >=0.25 s dan >=2 sampel -> PRESENT.
5. Tidak ada deteksi atau bagian tubuh tertutup -> bukan bukti melepas APD.
   Bukti terkonfirmasi sebelumnya CACHED sampai TTL 2 s, lalu UNKNOWN, bukan ABSENT.
6. Konflik, identitas ambigu, person hilang, frame lama/duplikat atau fault
   membuang evidence sesuai aturan tracker. IoU adalah ID geometris sementara,
   bukan pengenal identitas manusia/re-identification.

Telemetry item.transition berisi previous/current/cause. Dashboard menampilkan
riwayat maksimum 48 event. Alarm candidate tetap hasil aturan SIMULASI, tidak
pernah dikirim ke actuator. Timing tersebut belum dikalibrasi untuk bengkel.

## 2. Heartbeat Pico saja â€” DITAHAN sampai masalah panas diperiksa

Jangan menjalankan instruksi live ini sekarang hanya karena file tersedia.
Pastikan operator siap mengawasi, board/suplai/konektor diperiksa dan thermal
issue ditangani. Tidak ada angka temperatur cutoff yang diasumsikan universal.
Jika kembali sangat panas, hentikan tes dan lepaskan power secara aman; jangan
menyentuh komponen panas atau mencabut/memasang FPC saat masih berdaya.

File yang kelak di-upload:
D:\RUDY\HAIKAL\APDChecker\edge\luckfox\apd_debug_probe.sh.
Script POSIX sh hanya membaca uptime dan thermal_zone0, output JSON tiap detik,
default 10 sampel, maksimum 60. Tidak menyalakan kamera/AI atau mengubah service.
Nilai thermal mentah tidak dikonversi ke Celsius sebelum sensor/unit diverifikasi.
Sensor tidak tersedia => null, bukan aman. Script bukan proteksi thermal.

Setelah hardware dan device serial benar-benar diverifikasi, buka receiver PC
TERLEBIH DAHULU di terminal pertama:

~~~powershell
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\debug_apd_computer.py' --probe-only --thermal-checked --telemetry-file 'D:\RUDY\HAIKAL\APDChecker\docs\luckfox\debug\probe-live.jsonl' --duration 30
~~~

Flag --thermal-checked adalah pengakuan operator, bukan hasil pengukuran aplikasi.
Dashboard tidak pernah menjalankan ADB sendiri. Pengambilan data tetap manual
terpisah. CONTOH berikut hanya berlaku setelah pemeriksaan termal dan USB:
placeholder serial wajib diganti dengan satu device yang sudah diverifikasi;
jangan memilih sembarang device, jangan flashing.

~~~powershell
$serialPico = 'GANTI_DENGAN_SERIAL_PICO_YANG_SUDAH_DIVERIFIKASI'
& 'D:\RUDY\HAIKAL\APDChecker\platform-tools\adb.exe' -s $serialPico push 'D:\RUDY\HAIKAL\APDChecker\edge\luckfox\apd_debug_probe.sh' /tmp/apd_debug_probe.sh
# Jalankan HANYA bila push sukses dan operator masih mengawasi board:
& 'D:\RUDY\HAIKAL\APDChecker\platform-tools\adb.exe' -s $serialPico exec-out sh /tmp/apd_debug_probe.sh 10 | Add-Content -LiteralPath 'D:\RUDY\HAIKAL\APDChecker\docs\luckfox\debug\probe-live.jsonl' -Encoding utf8
~~~

File /tmp tidak dipasang sebagai service. Jangan menghubungkan Arduino.
Script tidak mematikan layanan kamera/AI yang mungkin sudah berjalan di board:
field ai_running=false merujuk pada probe ini, bukan audit proses sistem lain.

Receiver hanya membaca JSONL yang BARU ditambahkan setelah startup; history
lama dilewati. Partial/invalid/oversized JSON, sequence mundur/duplikat dan uptime
mundur tidak dianggap heartbeat baru. Setelah >3.5 s tanpa receipt baru, status
STALE. Ini mengukur freshness RECEIPT PC, bukan waktu capture/sensor yang bisa
terjamin; jangan memberi file backlog yang lama lalu menganggap board masih hidup.
Jika board reboot, restart receiver dengan sesi/file baru. Jangan truncate/replace
file yang sedang dipantau. Receiver bukan link safety yang terautentikasi.

## 3. Preview kamera ke PC â€” SETELAH heartbeat/thermal stabil

Pastikan kamera dan URL stream aktual sudah diverifikasi dalam sesi hardware aman.
Aplikasi tidak menebak IP/port/path, tidak memulai service kamera/RTSP di Pico,
serta tidak melakukan model inference. Jangan menjalankan contoh URL placeholder.

~~~powershell
$urlKamera = 'GANTI_DENGAN_URL_RTSP_YANG_SUDAH_DIVERIFIKASI'
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\debug_apd_computer.py' --rtsp $urlKamera --thermal-checked --duration 30
~~~

Tambahkan --telemetry-file dengan path di atas bila ingin heartbeat dan video
bersamaan. Collector heartbeat harus kembali dijalankan manual untuk sesi baru.
Preview menggunakan OpenCV host dengan open/read timeout dan JPEG ukuran terbatas.
Frame ditampilkan apa adanya; orientasi/FPC tidak diasumsikan dari preview ini.
PC receipt age >2 s menyembunyikan gambar. Read/encode error atau kamera putus
mengosongkan preview. Receipt frame bukan bukti frame capture sensor benar-benar
baru: buffer RTSP/latency perlu dievaluasi sebelum inferensi temporal asli.

Live preview TIDAK menampilkan state APD sintetis pada video nyata: semua state
APD tetap UNKNOWN karena detektor tidak berjalan. Status heartbeat bukan sinyal
pelanggaran APD. Arduino/hardware_outputs selalu false dalam semua mode.
Berhentinya viewer PC tidak menghentikan service stream yang berjalan pada Pico.

## Regresi

~~~powershell
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\test_apd_offline.py'
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\check_apd_tracking.py' --replay 'D:\RUDY\HAIKAL\APDChecker\tests\fixtures\apd_workshop_replay.jsonl'
~~~

Tes memakai deteksi sintetis, HTTP loopback dan fake OpenCV. Tidak mengakses board.
Keberhasilan tes tidak mengukur akurasi AI, suhu nyata, kualitas stream atau FPS Pico.
