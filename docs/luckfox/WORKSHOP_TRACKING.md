> Update 11 Oktober 2026: tracker memiliki port C bounded dan frame builder
> HOST-tested (598 frame parity + 1.024 vector geometri + boundary tests).
> Belum terintegrasi kamera/NPU di Pico. Ringkasan status hardware terbaru ada di
> PRODUCTION_PROGRESS.md; paragraf bertanggal 10 Oktober di bawah adalah historis.
> Koordinat tracker wajib full-frame **view tegak** setelah rotasi terkalibrasi,
> bukan sensor mentah terbalik. Lihat RV1103_BACKEND.md.

# Bengkel: tracking dan cache APD per orang

10 Oktober 2026. **Prototipe Python offline di laptop, bukan aplikasi yang sudah
berjalan di Luckfox.** Tidak ada akses USB, ADB, kamera, UART, GPIO, relay ataupun
siren pada perubahan ini. Jangan menyalakan kembali board untuk menjalankan tes ini.
Penyebab panas berlebihan belum diselesaikan.

## Kebutuhan yang sudah dikonfirmasi pengguna

| Item | Warna indikator | Makna menyala |
|---|---|---|
| Rompi | Hijau | Bukti memakai rompi terkonfirmasi untuk orang target |
| Sepatu | Kuning | Bukti memakai sepatu terkonfirmasi untuk orang target |
| Helm | Merah | Bukti memakai helm terkonfirmasi untuk orang target |

Ketiganya boleh menyala **bersamaan**. Warna adalah identitas item, bukan level
bahaya. Lampu merah menyala tidak otomatis berarti pelanggaran. Tidak ada warna
indikator khusus alarm yang sudah ditetapkan dalam perubahan ini.

Lokasi adalah bengkel dengan orang lalu-lalang. Sistem tidak boleh mengharuskan
orang berhenti untuk bisa mulai melacak, tetapi jendela pengamatan harus cukup
untuk konfirmasi. Orang yang terlalu cepat melintas bisa berakhir UNKNOWN;
prototipe tidak mengubah kekurangan bukti menjadi pelanggaran.

Konfirmasi kebutuhan ini BUKAN konfirmasi akurasi, angka timing, kelayakan termal,
atau kesiapan produksi. Masker tidak termasuk kebijakan bengkel yang baru.
Profil helmet/mask yang lama tetap tersedia untuk regresi model lama saja.

## Pemisahan tanggung jawab

1. Kamera/backend: frame baru dengan ID capture, waktu capture monotonik, kondisi
   kamera/model dan koordinat box yang benar setelah transformasi gambar.
2. Detektor: person dan bukti APD positif/negatif; confidence di atas ambang.
3. Adapter visibility: apakah bagian tubuh yang relevan benar-benar dapat dinilai.
4. Tracker/cache: hubungkan pengamatan ke track sementara, simpan bukti per item
   dengan asal/waktu/masa berlaku, buang saat identitas tidak dapat dipercaya.
5. Aturan alarm: bukti negatif eksplisit + visibility + konfirmasi temporal.
6. Pemilih target: tiga lampu menggambarkan satu orang target, tidak campuran orang.
7. MCU: kelak menangani lampu/sirene/watchdog secara deterministik. Belum diubah.

Lapisan 3 dan implementasi perangkat untuk lapisan 1/2 **belum ada**. Tes memakai
metadata visibility sintetis yang disuplai fixture, bukan hasil estimasi kamera.
Box person yang berada di dalam gambar saja tidak membuktikan kaki terlihat:
kaki dapat tertutup meja, objek, orang lain, atau box yang sebenarnya terpotong.

## Data yang disimpan per track dan per item

- ID track sementara, box, waktu terakhir orang terlihat.
- State: PRESENT / ABSENT / UNKNOWN.
- Observation baru: PRESENT / ABSENT / UNKNOWN / CONFLICT.
- Reason, misalnya NOT_VISIBLE atau NEGATIVE_VISIBILITY_UNVERIFIED.
- Source: FRESH / CACHED / NONE.
- Timestamp terakhir bukti langsung, confidence, waktu kedaluwarsa.
- Kandidat konfirmasi, waktu mulai, jumlah sampel frame baru.

**NOT_VISIBLE adalah alasan pengamatan, bukan bukti ABSENT.** Sepatu yang sudah
terlihat boleh masih PRESENT/CACHED saat kaki sesaat tertutup. Jika sepatu belum
pernah terlihat, hasilnya UNKNOWN dengan alasan NOT_VISIBLE. Setelah TTL habis,
PRESENT/CACHED kembali UNKNOWN, bukan berubah menjadi ABSENT.

## Aturan bukti

- Bukti harus dapat diasosiasikan ke tepat satu orang; posisi relatif item dipakai
  sebagai filter kasar kepala/torso/kaki, bukan estimator visibility tervalidasi.
- Tidak mendeteksi sepatu/helm/rompi **tidak sama** dengan mendeteksi tidak memakai.
  Bahkan metadata OBSERVABLE ditambah detektor yang tidak menemukan item tetap
  UNKNOWN tanpa metode absensi yang sudah divalidasi.
- no_* baru dipakai sebagai bukti negatif bila metadata item adalah OBSERVABLE.
- Konflik positif/negatif pada item yang sama membuang cache item itu.
- Bukti baru yang berlawanan membatalkan kesimpulan lama segera, kemudian status
  baru harus dikonfirmasi; bukan terus menampilkan lengkap selama memakai/lepas.
- UNKNOWN memutus kandidat yang belum terkonfirmasi, tetapi boleh menyimpan bukti
  yang sebelumnya sudah terkonfirmasi sampai TTL. Membaca cache tidak menambah
  sampel konfirmasi dan tidak memperpanjang TTL.
- Alarm_candidate hanya true untuk item ABSENT terkonfirmasi dengan bukti negatif
  langsung pada frame sekarang. ABSENT/CACHED saja tidak membuat kandidat alarm.
- Satu item negatif terkonfirmasi cukup untuk kandidat pelanggaran meskipun item
  lain belum diketahui. UNKNOWN saja tidak pernah memulai kandidat alarm.
- alarm_candidate hanya hasil SIMULASI aturan, bukan perintah membunyikan sirene.
  Cooldown, durasi bunyi, ACK, watchdog dan kebijakan fault MCU belum dibuat.

## Angka awal untuk simulasi, bukan angka produksi final

| Parameter | Nilai | Maksud |
|---|---:|---|
| Bukti positif | >=2 frame baru selama >=0,25 detik | Indikator tidak mengikuti satu frame saja |
| Bukti negatif | >=3 frame baru selama >=1,5 detik | Tidak langsung berteriak dari satu prediksi |
| TTL bukti terkonfirmasi | 2 detik sejak bukti langsung terakhir | Cache tidak bertahan selamanya |
| Gap inferensi maksimum | 0,75 detik | Gap lebih lama menghapus track/cache |
| Usia frame maksimum | 0,75 detik | Saat received_at disuplai, frame basi ditolak |
| Handle track hilang | <1 detik | ID boleh dipertahankan singkat, bukti tetap dihapus |
| Kapasitas | 8 handle track, 64 deteksi APD per frame | Overflow menjadi MODEL_ERROR |

Kedua syarat, waktu **dan** jumlah sampel, harus terpenuhi. Kamera/backend nyata
wajib menyuplai received_at dari clock monotonik yang sama dengan captured_at;
default received_at=captured_at hanya kemudahan replay sintetis, bukan verifikasi
freshness pada perangkat. ID dan timestamp harus benar-benar milik capture, bukan
angka baru yang ditempelkan ke gambar/inferensi lama.

Angka di atas perlu dikalibrasi dengan durasi lintasan dan laju inferensi nyata.
Jika seseorang terlihat kurang dari 1,5 detik, sistem ini memang bisa tidak
mengonfirmasi negatif. Jangan menurunkan ambang hanya untuk memperoleh alarm;
uji false alarm dan pelanggaran yang terlewat pada rekaman berlabel.

## Identitas sementara dan batasannya

Tracker sekarang menggunakan kecocokan overlap box (IoU) yang konservatif:

- Kecocokan satu-ke-satu dapat mempertahankan ID dan bukti.
- Beberapa kandidat atau overlap orang yang besar membuat identitas ambigu:
  handle terkait dibuang, track baru UNKNOWN, bukti baru di frame ambigu tidak
  digunakan untuk konfirmasi.
- Saat person tidak terdeteksi pada satu frame inferensi, bukti semua item track
  tersebut dihapus. Reacquisition singkat dapat memakai ID lama tetapi tidak
  mewarisi cache APD. Occlusion item saja berbeda: selama person tetap terdeteksi
  dan match tidak ambigu, cache item dapat dipertahankan sampai TTL.
- Gap inferensi, stale/duplicate frame, kamera/model fault dan invalid detection
  menghapus cache. Fault bukan COMPLIANT/SAFE.

Ini **bukan pengenal identitas manusia** atau jaminan bahwa orang yang keluar lama
lalu kembali adalah orang yang sama. IoU saja juga bisa salah pada pergantian
posisi antarframe tanpa overlap yang tertangkap kamera. Uji crossing nyata,
crowding, deteksi yang hilang dan motion blur masih wajib. Tidak ada face
recognition, embedding re-identification, atau database identitas permanen.

## Tiga lampu saat beberapa orang terlihat

Prototipe memilih otomatis hanya jika tepat satu person terlihat. Jika lebih dari
satu dan tidak ada target terpilih, mode MULTIPLE_PEOPLE mengembalikan nilai null
untuk ketiga lampu. Target dapat dipilih dengan selected_track_id; hanya item dari
track itu yang ditampilkan. Target hilang tidak otomatis diganti ke orang lain.

Di JSON: true=PRESENT, false=ABSENT, null=UNKNOWN/tidak ada target yang jelas.
Ini **nilai debug**, bukan pola PWM/blink fisik yang sudah disetujui. Cara membedakan
UNKNOWN dari ABSENT pada lampu (misalnya berkedip vs mati) belum ditetapkan.

Usulan untuk tahap berikutnya: satu zona pemeriksaan pada jalur lewat dan satu
track target aktif. Aturan urutan target/antrean, penanganan orang berdampingan,
serta apakah lampu memakai agregasi konservatif harus diputuskan sebelum firmware.
Dilarang OR lintas orang: rompi A + sepatu B + helm C tidak berarti ada orang
ber-APD lengkap. Alarm_candidate tetap dihitung per track; selector hanya untuk
lampu debug. Kelayakan alarm di zona/arah gerak belum diimplementasikan.

## Kebutuhan model yang belum terpenuhi

Daftar kelas PPE lokal yang dipakai validator lama mencakup helmet/no_helmet dan
shoes/no_shoes, tetapi **tidak vest/no_vest dan tidak person**. Detektor person
terpisah dipakai hanya di validator host. Profil bengkel mengecek kontrak label
ini dan menyatakan NOT READY. HostDetector menolak kebijakan required yang tidak
didukung kelas model; tidak memetakan mask menjadi vest atau memakai fallback.

Fixture boleh menyimulasikan kelas vest untuk menguji aturan. Itu bukan hasil AI.
Label shoes belum membuktikan kemampuan membedakan sepatu safety dari sepatu
biasa/sandal, kondisi kedua kaki, atau pemakaian yang benar. Definisi PPE sepatu
bengkel dan anotasi dataset perlu ditetapkan. Hal serupa berlaku untuk jenis
rompi dan pemakaian helm. Label tersedia bukan bukti akurasi.

Update 11 Oktober: core/session C lama tetap referensi legacy. File terpisah
workshop_tracker.c/.h sekarang mem-port logika bengkel dengan fixed-capacity,
visibility gate, TTL/cache, konfirmasi pasang/lepas dan freshness tick. HOST build
Zig 0.13.0 lulus; **598 frame sintetis cocok dengan referensi Python** (replay bengkel,
demo pasang/lepas, multi-orang, konflik dan 512 frame stress seed 1103). Struktur
ws_tracker HOST 1.096 byte; ini BUKAN total stack/buffer/runtime/ABI RAM di RV1103.
Tick wajib dipanggil di antara inferensi agar report basi tidak dipertahankan.
Tidak ada model RKNN, adapter kamera/NPU, ARM binary atau output hardware.
Lihat PRODUCTION_PROGRESS.md dan debug/native-tests-20261011.log.

## Jalankan tanpa Luckfox dan tanpa Arduino

~~~powershell
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\test_apd_offline.py'

& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\check_apd_tracking.py' --replay 'D:\RUDY\HAIKAL\APDChecker\tests\fixtures\apd_workshop_replay.jsonl'
~~~

Output replay: D:\RUDY\HAIKAL\APDChecker\docs\luckfox\tracking-check\replay.json.
Kebijakan: D:\RUDY\HAIKAL\APDChecker\config\apd_workshop.json.
Implementasi: D:\RUDY\HAIKAL\APDChecker\python\apd_runtime\tracking.py.

Replay 29 frame sintetis meliputi kaki belum terlihat, APD lengkap, kaki tertutup,
cache kedaluwarsa, bukti no_shoes yang butuh konfirmasi, orang keluar/orang baru,
beberapa orang, crossing ambigu, fault, dan recovery. Unit tests juga mencakup
urutan deteksi berubah, konflik, kandidat negatif antarorang tidak tercampur,
frame duplikat/basi, batas kapasitas dan label rompi model yang tidak didukung.

Tes ini tidak mengukur akurasi AI, tracker pada video nyata, latency/FPS NPU,
atau temperatur board. Output hardware selalu false. Ini langkah logika sebelum
pengumpulan/labeling video bengkel dan deployment perangkat yang aman.


## Pasang/lepas dan debugging komputer

Telemetry item sekarang juga memiliki transition (previous/current/cause). Tes
regresi mencakup melepas lalu memasang ulang rompi, sepatu dan helm pada track
yang sama; bukti baru berlawanan langsung menjadi UNKNOWN sebelum dikonfirmasi.
Panduan mode demo, probe-only dan camera-preview: D:\RUDY\HAIKAL\APDChecker\docs\luckfox\PC_DEBUG.md.
Tidak ada upload/deployment Pico atau akses Arduino pada sesi pembuatan ini.
