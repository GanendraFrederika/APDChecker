# Changelog

## [3.3.0] — 2026-10-28

### Diubah
- **Sarung tangan dihapus**: APD = helm, rompi, sepatu. Gestur: jempol → angguk; jempol dari
  orang yang APD-nya kurang → geleng sekali + "Mohon lengkapi APD"; melambai → sapa.
- **Model APD diganti** setelah evaluasi di 141 foto uji construction-ppe:
  helm AP50 0,00 → 0,78, rompi (sebelumnya hanya warna) → 0,74, sepatu 0,00 → 0,52.
  Detail: `docs/sentinel/ppe_model_eval.md`.

### Ditambahkan
- `scripts/eval_ppe.py` (bandingkan model), `scripts/scan_pt.py` (tolak file .pt berbahaya),
  `scripts/collect_workshop.py` (kumpulkan foto bengkel berlabel saran AI),
  `scripts/train_ppe.py` + `training/train_ppe_colab.ipynb` (fine-tune 4 kelas proyek).
- Endpoint dashboard `/raw.jpg` (gambar tanpa anotasi untuk data latih).

## [3.2.0] — 2026-10-27

### Diperbaiki (diuji di rig asli)
- **Arduino reset terus tiap beberapa detik.** Penyebabnya: gangguan USB sesaat saat servo
  menarik arus (tegangan turun ke ~4,3 V) membuat program PC menutup lalu membuka ulang
  port serial, dan membuka port Uno = reset (DTR). Sekarang port dibuka dengan DTR mati
  (tidak mereset Arduino), gangguan sesaat dicoba ulang tanpa menutup port, dan reboot
  Arduino ditangani tanpa membuka ulang port. Tes rig: 0 reboot dari 48 gangguan USB.
- **Servo pan "patah-patah / tretet".** Setiap reset membuat servo meloncat ke pose lama
  dan meluncur lagi. Ditambah: pose servo terakhir disimpan di RAM yang tidak dihapus saat
  reset, jadi setelah reset servo mulai tepat di posisinya. Akselerasi dibuat lebih lembut
  (pan 300, tilt 200 °/s²): puncak arus servo lebih kecil.
- **Alarm berisik / noise.** Pengatur volume lama memutus nada 100 kali per detik (dengung
  100 Hz). Nada sekarang dibuat interrupt Timer2 dengan duty-cycle (tanpa dengung),
  envelope lembut (attack, decay, release) dan kurva volume audio. Alarm diganti nada
  minor C-Eb-G yang tenang seperti monitor rumah sakit, plus satu pengumuman suara
  "Mohon lengkapi APD" dari laptop. Volume default 50 %.
- **"LINK AI PUTUS" berkedip.** Bug jam: frame diberi cap waktu sesudah `millis()` loop,
  selisih unsigned membungkus ke ±49 hari. Loop kini membaca jam sesudah memproses frame
  dan perbandingan waktu memakai aritmetika bertanda.
- PC sleep mematikan USB: aplikasi kini menahan PC agar tidak sleep selama berjalan.
- Aplikasi tidak lagi keluar bila Pico belum tersambung: menunggu dan menyalakan kamera
  begitu Pico muncul; dashboard dan preview LCD tetap hidup tanpa kamera.

### Ditambahkan
- **Batas tilt 170° saat menoleh kanan** (atap tilt ikut pan, `MAXR`), dijaga firmware
  termasuk saat animasi; jalur "turunkan dulu, baru putar". EEPROM versi 4.
- **Preview LCD 16x2 di dashboard**: Arduino mengirim teks LCD-nya (`LCD,...`).
- **Kalibrasi kamera otomatis dari gerakan servo** (tombol "Kalibrasi kamera" /
  `--calibrate`): servo bergerak ±5°, pergeseran gambar diukur, lalu rotasi 90°-an,
  kemiringan tabung (roll) dan FOV dihitung serta disimpan ke config. Tidak perlu orang.
- **Rotasi otomatis dari orang tegak** + tombol "Putar kamera 90°".
- Kipas tanpa DS18B20 = **mati** (sensor masih dipesan). Begitu sensor dicolok, firmware
  mendeteksinya sendiri dan kipas jadi otomatis tanpa upload ulang. Kipas Pico ikut suhu
  SoC Pico.
- `scripts/sentinel_hil.py`: tes hardware-in-the-loop (patroli, lock, ikuti, grup,
  pelanggaran + alarm, animasi, cari, kipas, LCD, reboot, kehalusan) di rig asli, atau
  `--sim` dengan firmware core yang sama dikompilasi untuk PC. Rig asli: 24/24 lulus.

### Catatan
- Firmware 31.182 / 32.256 byte.
- Pico masih hilang dari USB beberapa menit setelah kamera menyala: dugaan daya/kabel USB.

## [3.1.0] — 2026-10-26

### Ditambahkan
- **Gestur tangan** (MediaPipe): jempol + sarung tangan → angguk "iya" (cooldown 5 detik)
  + salam; jempol tanpa sarung tangan → geleng "tidak" sekali lalu alarm; telapak terbuka
  → sapa. Tangan dipasangkan ke orang terdekat lewat titik pergelangan.
- **Sarung tangan** sebagai item ke-4 (opsional: ditampilkan, tidak memicu alarm sendiri).
  Toggle debug "anggap pakai sarung tangan" di dashboard dan `--assume-gloves`.
- **Suara salam** bahasa Indonesia di speaker laptop (Halo, Hai, Selamat
  pagi/siang/sore/malam, Hati-hati ya, A P D lengkap, Mohon lengkapi A P D).
- **Nada di speaker rig**: chime angguk/geleng/sapa, sirine dua nada; **volume** 0–100 %
  (perintah `VOL`, slider dashboard, default 50 %).
- **Animasi servo** di firmware: angguk, geleng, celingak-celinguk, sapa. Selalu di dalam
  zona aman dan kembali tepat ke pose awal.
- **Protokol SLP/1.1**: frame `S` 15 field (item sarung tangan, fx, fx_id, izin suara);
  frame SLP/1.0 12 field tetap diterima.
- `config/sentinel.json`: rotasi kamera, arah servo, patroli, suara, volume.
- `python/sentinel/luckfox.py`: forward RTSP otomatis, profil kamera ringan 10 fps
  (backup otomatis), watchdog pulih sendiri setelah cabut-colok USB.
- Tes: `tests/test_sentinel.py` (15 tes) + tes native firmware diperluas.

### Diubah
- **Gerak servo halus**: profil trapesium + dua tahap penghalus eksponensial di firmware
  (ease-in/ease-out, perubahan kecepatan maks 84 dd/s per frame, sebelumnya 1200).
- **Kamera tenang**: dead zone ±6°, re-center sampai ±2° lalu diam, aim point difilter;
  orang berdiri dengan goyang 1–2 cm tidak menggerakkan servo sama sekali.
- **LCD**: teks normal berganti maksimal tiap 3 detik; alarm/putus link langsung menimpa;
  teks tidak berkedip (kedipan dipindah ke LED).
- **Orientasi kamera**: sensor di tabung terpasang 90°; gambar diputar 90° CW (diverifikasi:
  model pose hanya menemukan orang tegak dengan 14 titik pada putaran ini).
- Deteksi rompi hi-vis kini mencakup oranye kemerahan; helm punya cadangan warna mahkota
  kepala bila model melewatkannya; visibilitas kepala tidak lagi gagal saat badan menyentuh
  tepi atas frame.
- Home tilt 180° (rig sejajar orang saat development).
- Firmware dipadatkan agar muat di Uno (32.110 / 32.256 byte): easing polinomial tanpa
  sin/cos, `LOAD` dihapus (reboot memuat EEPROM), `#TOUR` dihapus.

### Diperbaiki
- Mode berganti-ganti cepat (I→A→S→G) akibat deteksi berkedip: masa tenggang 0,4 detik dan
  histeresis grup 0,6 detik.
- Servo mengarah terbalik akibat kamera terpasang miring.

## [3.0.0] — 2026-10-24

### Ditambahkan
- Arsitektur baru **APD Sentinel**: person-lock pan-tilt menggantikan patroli 1 menit buta.
- Firmware Uno `apd_sentinel` dengan core C teruji di PC: protokol SLP/1 (CRC-8, token sesi,
  seq), zona aman trapesium hasil ukur, link-loss → alarm mati + kembali home, kalibrasi
  lewat console + EEPROM, memori pose (tanpa sentakan saat dinyalakan), LCD bit-bang,
  DS18B20 + kipas MOSFET, monitor Vcc, watchdog.
- Otak AI di laptop: pose (17 titik) + model APD + rompi warna, tracker di ruang sudut
  servo, brain (patroli, akuisisi, lock, grup, pelanggar, cari), dashboard web.

### Diperbaiki
- `python/apd_runtime/live_camera.py` terpotong (SyntaxError) sehingga
  `JALANKAN_SISTEM_APD.bat` tidak bisa jalan.

### Dirapikan
- Workspace dibersihkan: APDCheckORI, paket migrasi chat, zip Blender 404 MB, `.git` rusak,
  skrip tes lama, dan model duplikat dipindah ke `_archive/` (tidak ada yang dihapus).
