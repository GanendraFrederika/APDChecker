# Changelog

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
