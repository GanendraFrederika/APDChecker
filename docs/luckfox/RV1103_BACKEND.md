> Candidate RKNN lifecycle added: [RKNN_ENGINE_CANDIDATE.md](RKNN_ENGINE_CANDIDATE.md).
> HOST mocks only, no matching board ABI/camera/model acceptance yet.

> Update 11 Oktober 2026: runtime ELF32 ARM hard-float/uClibc 1.0.31,
> driver NPU 0.8.2, librknnmrt static string 1.4.1b9; latest SDK compatibility
> unverified. Operator confirms physical reconnect. 300 s camera passed and
> shipped vendor NPU interrupt activity observed, NOT APD model inference.
> Decoder grid portable HOST-tested: GRID_DECODER.md. Camera/RKNN production
> adapter still missing. See PRODUCTION_PROGRESS.md / VENDOR_NPU_TEST.md.

# Jalur backend RV1103: status implementasi dan build

11 Oktober 2026. **Belum aplikasi AI yang berjalan di Pico.** Tidak ada firmware,
model RKNN atau binary ARM yang diunggah pada penambahan ini. Arduino tidak diakses.

## Bagian integrasi yang sudah dibuat dan HOST-tested

- `edge/luckfox/backend_frame.{h,c}`: membangun `ws_frame` dari box post-NMS,
  ID/timestamp capture dan metadata visibility yang disuplai backend.
- Tujuh label eksplisit (urutan ID boleh berbeda): `person`, `vest`, `no_vest`,
  `shoes`, `no_shoes`, `helmet`, `no_helmet`. Tidak ada fallback COCO, alias masker
  menjadi rompi, atau anggapan item tidak terdeteksi berarti ABSENT. Profil tujuh
  kelas ini adalah kontrak adapter awal, bukan syarat semua arsitektur masa depan.
- Gunakan resize integer dan padding yang BENAR-BENAR dipakai pada frame tersebut.
  `apd_unletterbox_box()` menghasilkan koordinat full-frame **view tegak setelah
  rotasi** untuk tracker. Kepala/torso/kaki menggunakan posisi vertikal di view ini.
- `apd_inverse_box()` membalik rotasi ke koordinat sensor mentah untuk overlay saja.
  Jangan feed sensor terbalik/menyamping ke tracker. Rotasi harus dikalibrasi dari
  pemasangan nyata; nilai historis 180 derajat bukan jaminan semua pemasangan.
- Input box harus finite, confidence 0..1, luas positif, berada dalam input model.
  Box yang seluruhnya ada di padding dilewati; box melintasi padding dipotong.
  Pemotongan ini **tidak** membuktikan bagian tubuh terlihat/observable.
- Kelas salah/duplikat, metadata invalid atau overflow mengosongkan frame dengan
  MODEL_ERROR. Batas 8 person, 64 equipment, 72 raw detection: tidak diam-diam
  memilih top-K dan melaporkan semua orang aman saat kapasitas terlampaui.
- Tidak ada heap di builder/tracker; belum ada pengukuran total stack/media/RKNN RAM
  atau ABI ARM. RK-MPI capture, resize pixel, postprocess tensor, NMS, visibility,
  camera/NPU lifecycle dan watchdog masih belum diimplementasi/diintegrasi.

## Bukti pengujian

`debug/native-tests-20261011-backend.log` adalah build/run HOST dengan Zig 0.13.0,
C99 `-Wall -Wextra -Werror -pedantic`:

- 598 frame parity C/Python sintetis untuk tracker.
- 1.024 box geometri sintetis (empat rotasi; resolusi landscape/portrait;
  resize rounded dan padding asimetris). Python forward corner transform dibanding
  C inverse/unletterbox. Toleransi absolut 0,025 piksel hanya untuk vector ini.
- Label order, padding, malformed input, overflow, visibilitas setelah weak-person
  filtering, negative dwell dan re-wear cancellation diuji dengan builder + tracker.
- Test boundary tracker untuk null input/config invalid, stale tick, waktu mundur,
  NaN, kapasitas penuh/lebih dan ID exhaustion. Null input sekarang tidak boleh
  mempertahankan report positif lama; evidence dibuang menjadi MODEL_ERROR.

Ini **bukan** kalibrasi kamera, akurasi detektor, NPU throughput atau uji bengkel.

```powershell
& .\.venv\Scripts\python.exe scripts/check_native_core.py --zig .tools/ziglang-0.13.0/ziglang/zig.exe --workshop
& .\.venv\Scripts\python.exe scripts/test_apd_offline.py
```

## Referensi primer untuk langkah build berikutnya

Source Rockchip diambil **pada commit yang dicatat** di
`debug/build-preflight/rockchip-backend-reference.json`; setiap file memiliki hash.
File referensi disimpan sebagai `.txt`, tidak dieksekusi, tidak otomatis diterapkan
ke board. Referensi terbaru tidak membuktikan cocok dengan runtime board lama.

Temuan dari source yang tersimpan:

1. YOLOv5 CMake memilih `yolov5_rv1106_1103.cc` untuk `rv1103`/`rv1106`.
2. README menyebut compiler `arm-rockchip830-linux-uclibcgnueabihf` untuk keduanya.
   Zig HOST tidak menggantikan toolchain SDK/ABI ini.
3. Backend menggunakan RKNN native input attributes, input UINT8/NHWC, memory
   stride dan zero-copy API. Output quantized diproses sebagai INT8 pada branch ini.
4. Contoh punya buffer satu input/tiga output, asumsi anchor/stride YOLOv5, dan
   postprocess `OBJ_CLASS_NUM=80` + label COCO. **Tidak boleh langsung digunakan**
   untuk model tujuh kelas kita. Validasi tensor/count/size/type/stride/scale/zp
   dan anchors sesuai export diperlukan sebelum alokasi/decoding.
5. README membedakan optimized raw-grid export dari output YOLO biasa. Mengganti
   file `.pt` atau nama model saja tidak membuat decoder kompatibel.
6. Source demo bukan production lifecycle: beberapa error-path init dapat return
   setelah context/memory dialokasikan. Jangan menyalin begitu saja; adapter kita
   harus punya cleanup parsial idempoten, pemeriksaan semua alokasi/tensor dan
   bounded capture timeout. Belum ada cleanup RKNN nyata yang diuji di sini.

## Urutan kerja yang tidak boleh dilompati

1. Pulihkan ADB secara diawasi; verifikasi identity, idle, thermal dan log USB.
   Ambil runtime/API/library/SDK/ELF ABI inventory read-only. Jangan menjalankan
   model/camera otomatis setelah koneksi kembali.
2. Siapkan lingkungan Linux terpisah untuk RKNN-Toolkit2/conversion dan SDK
   Rockchip yang kompatibel. Tidak install Torch/Ultralytics di Pico Mini B.
3. Tetapkan dataset dan definisi APD. Model lama tidak punya rompi/person dan
   tidak bisa dipakai untuk klaim kebutuhan bengkel ini.
4. Latih/evaluasi kandidat kecil yang kompatibel RV1103 (YOLOv5n-family candidate,
   bukan janji performa). Pakai export output yang sesuai decoder; simpan source,
   versi, license, class-order dan SHA256. Verifikasi float vs INT8 pada holdout.
5. Baru implementasi camera/media-buffer/RKNN + visibility; ukur RAM, latency,
   inference gap, suhu dan akurasi. Target inferensi 3 FPS bukan bukti kamera
   bisa capture 3 FPS: capture terakhir terukur 10 FPS.
6. Uji shutdown/error/reboot/rollback dan MCU secara terpisah sebelum outputs
   dapat diaktifkan. Kontrak dan tes sintetis tidak membuka deployment gate.
