# Decoder grid tujuh kelas — kandidat, bukan AI produksi

`edge/luckfox/grid_decoder.{h,c}` hanya postprocess C99 tanpa RKNN/camera IO.
Tidak diunggah atau dijalankan di Pico. Jangan menjalankan weights YOLOv8 lama
melalui decoder ini atau menganggap tes sintetis membuktikan akurasi APD.

## Kontrak yang diterima

- Optimized YOLOv5 output post-sigmoid, INT8 affine, logical NCHW; satu batch,
  tiga head dengan stride 8/16/32, tiga anchor/head, tujuh kelas = 36 channel/head.
  Runtime adapter belum ada: harus memeriksa count/type/layout/dims dan memastikan
  native packing cocok. Tidak menerima NHWC/NC1HWC2/logits/YOLOv8/DFL.
- Input sampai 1024x1024, grid sampai 128x128; ukuran dibagi stride tepat.
  Ini batas software, bukan rekomendasi resolusi atau bukti RAM/performa Mini B.
- Data pointer + byte_count + row/channel stride eksplisit. Padding fisik tidak
  dibaca; ukuran logical terakhir diperiksa dengan arithmetic anti-overflow.
  Anchor/scale/zero-point HARUS berasal dari export/model + runtime attributes.
- Skala probability positif sampai 1/16; rounding tolerance setengah scale,
  kemudian clamp 0..1. Semua logical value divalidasi termasuk low objectness.
  Ini tidak dapat membuktikan graph benar-benar sigmoid; manifest export wajib.
- xy = (2*p_xy - 0.5 + grid)*stride; wh = (2*p_wh)^2*anchor.
  Score = objectness * max class probability. Single-label argmax, tie ID rendah.
  Ini pilihan kebijakan decoder, belum diterima terhadap model nyata.
- Clipping input-plane sebelum NMS; sort score menurun stabil, tie urutan
  head/anchor/row/column. NMS class-aware, suppress hanya jika IoU > threshold.
  Kelas positif/negatif tidak saling suppress; konflik diteruskan ke tracker.

## Batas dan error

Workspace caller-owned tanpa heap, kandidat maksimum 256 **sebelum NMS**.
Output maksimum 72 mengikuti frame builder; overflow = false/count 0, semua
output dibuang, bukan truncation top-K. Batas ini dapat perlu direvisi berdasarkan
crowded-site data, tetapi tidak boleh dilonggarkan tanpa pengujian RAM/latency.
Caller harus map false ke MODEL_ERROR dan segera invalidasi tracker/MCU report.

HOST workspace 6.664 B, bukan total stack/ARM ABI. Simpan dalam context milik
backend, bukan stack kecil thread dan bukan singleton sharing antar frame.
Input/workspace/output/count tidak boleh alias. Tidak ada estimasi total kebutuhan
RAM camera/RKNN dari angka ini. Lifetime pointer/output harus dijaga adapter.

Visibility person selalu UNKNOWN. Box berada di frame/model tidak membuktikan
helm/torso/kaki observable; no_item sendiri tidak cukup memicu ABSENT/alarm.
Gunakan frame transform nyata dan class permutation eksplisit di builder.

## Tes

- 256 tensor sintetis independen Python/C seed 11033336: probabilitas/quantization,
  anchors, padded row/channel, box clipping, stable ties, NMS.
- C boundary: invalid/null buffer/config, stride/byte-count/overflow/NaN,
  invalid probability even low score, opposing-label preservation, ties,
  kandidat >256, survivors >72, output capacity clear.
- Decoder -> builder -> tracker: negative helmet dengan UNKNOWN visibility tidak
  terkonfirmasi ABSENT; model fault menggugurkan report/cache. Output hard-disabled.
- Offline lima tes Python known-case/reference; total regresi 191 PASS.

`debug/native-tests-20261011-grid.log`, `debug/offline-tests-20261011-grid.log`.

Masih diperlukan: model tujuh kelas terpercaya, dataset/evaluasi bengkel,
float/INT8 parity holdout, export manifest, runtime/API matching, ARM SDK,
RK-MPI/RKNN cleanup/timeouts/visibility, performance/thermal soak dan MCU fisik.
Tidak ada model `.rknn` atau inference produksi saat ini.
