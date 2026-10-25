# Pan/tilt -- rancangan bertahap APDChecker

11 Oktober 2026. **HOST reference only; tidak menggerakkan motor**.

## Pilihan desain awal

Dua sumbu: pan kanan-kiri, tilt atas-bawah. Uno menangani motor; Luckfox
menentukan view/aturan AI dan kesehatan. Reserve kandidat D7/D8; bukan wiring
aktif dan bukan janji final kompatibilitas timer/library. Servo/driver supply,
model motor dan beban bracket belum diketahui; belum ada limit sudut/pulsa yang
layak dipakai pada hardware.

**Benturan legacy:** `apd_receiver.ino` memakai D8 sebagai LED alarm dan D11
sebagai satu servo. Reservation D7/D8 bukan perubahan pin yang boleh langsung
disambungkan ke rangkaian legacy; perlu revisi pin map/firmware terpisah.

**Fixed camera terlebih dahulu.** Orang yang berlalu-lalang bisa sudah keluar
sebelum scanning kepala/kaki selesai. Kamera yang digerakkan juga mengubah
referensi box IoU. Perbaikan framing fixed lebih dahulu daripada auto-follow.
Tidak menggabungkan kesimpulan APD orang antar-pose dengan IoU saja.

## Kontrak keselamatan cache

1. Sebelum gerak/crop/rotation/view berubah, naikkan epoch dan panggil
   `PersonPPETracker.invalidate_camera_view(epoch)` / `ws_invalidate_camera_view`.
   Ganti held report dengan hasil STARTING; jangan hanya clear cache internal.
2. Tidak reset frame ID/timestamp/track ID allocator. Buang queued view lama;
   frame dengan epoch lebih kecil ditolak dan cache dibuang.
3. Stamp `camera_view_epoch` dan `camera_view_unstable` ketika EXPOSURE, bukan
   ketika inference selesai. Jika view berganti selama exposure, drop frame.
4. Selama gerak, pose belum diketahui atau settling: unstable=true. Bahkan
   deteksi APD sempurna/negatif tidak boleh membangun cache/alarm pada view ini.
5. Sesudah ACK yang cocok dan settling tervalidasi: accept frame fresh, track
   baru dan debounce APD baru. Tidak mengembalikan cache hanya karena pulang home.
6. Default epoch=0/stable hanya kompatibilitas kamera fixed yang lama.
   Backend bergerak wajib mengirim metadata eksplisit. Frame builder C mereset
   metadata: adapter harus stamp metadata exposure setelah builder, sebelum tracker.
7. No auto retry pada timeout/stale ACK/backwards clock. Recovery eksplisit
   setelah pose diperiksa, epoch baru, settle, deteksi ulang.

## State machine reference

`STABLE -> MOVING -> SETTLING -> STABLE`.
Timeout atau input/ACK salah -> `FAULT`, view selalu unstable.
Default waktu prototype settle=1 s, timeout=3 s: **belum kalibrasi fisik**.
ACK tidak membuktikan posisi mekanik servo; motor macet tanpa feedback belum
bisa dipastikan hanya dari MCU mengatakan Servo.write() sudah dipanggil.

Implementasi: `python/apd_runtime/camera_view.py`. Tidak ada serial/GPIO/Servo,
angle command, automove atau driver MCU. Penambahan protokol motor/native
coordinator masih diperlukan. Metadata tracker C sudah tersedia.

### Contoh HOST, bukan resep menggerakkan servo

```python
tracker = PersonPPETracker()
gate = CameraMotionGate(tracker)
held_report = gate.begin_move(10.0)  # invalidate sebelum proposed motion
# Tidak ada perintah fisik yang dikirim oleh reference ini.
view = gate.snapshot(10.1)           # MOVING: unstable
# Adapter nyata nanti memberi ACK dengan epoch yang sama setelah gerak selesai.
gate.acknowledge_motion_complete(view.camera_view_epoch, 10.5)
settled_view = gate.snapshot(11.5)   # waktu settle prototype, bukan position proof
# Save settled_view bersama capture fresh dan teruskan tracker_kwargs saat update.
# Jika gate.snapshot/method raise: jangan pakai report sebelumnya sebagai SAFE.
```

View snapshot immutable, tetapi bukan fitur capture-start/end otomatis. Masa
exposure/capture queue nyata dan sinkronisasi motor/frame belum terintegrasi.

## Milestone fisik

1. Identifikasi servo posisi vs continuous rotation; spesifikasi dan supply.
2. Supply eksternal berkapasitas peak/stall, konektor/strain relief dan ground.
3. Bracket dua sumbu; limit kabel kamera, clearance, load dan posisi home.
4. Satu motor tanpa kamera dahulu, kemudian beban, kemudian dua sumbu.
5. Nonblocking ramp/deadband/limit pada MCU; protocol session/CRC/timeout.
6. Kamera fixed dengan AI tervalidasi; baru integrasikan gerak dan uji gate.
7. Uji exposure selama gerak/settle, return-home, stale ACK, stall/noise/brownout.

Jangan sweep 0..180 atau menyalakan motor saat boot tanpa commissioning. Satu
relay tetap untuk amplifier; pan/tilt bukan memerlukan relay tambahan per sumbu.
