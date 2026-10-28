# Evaluasi model APD (28-10-2026)

Data: Ultralytics **construction-ppe**, split *test*, 141 gambar (AGPL-3.0), label dipetakan
ke kelas proyek ini (helm, rompi, sepatu, orang). AP50 = luas kurva presisi/recall pada
IoU 0,5 (1,0 = sempurna). Waktu = CPU laptop proyek (AMD Athlon 3050U, 2 core).
Alat: `scripts/eval_ppe.py`. Semua file `.pt` diperiksa dulu dengan `scripts/scan_pt.py`.

| Model | Helm AP50 | Rompi AP50 | Sepatu AP50 | Tanpa-helm AP50 | ms/gambar | Lisensi |
|---|---|---|---|---|---|---|
| `ppe_yolov8n.pt` (lama) | **0,00** | tidak ada kelas | **0,00** | 0,00 | 153 @416 | ? |
| Hansung-Cho YOLOv8n | **0,78** | **0,74** | - | 0,13 | **104 @320** | MIT |
| melihuzunoglu YOLO11n | 0,60 | 0,67 | - | 0,04 | 151 @416 | AGPL-3.0 |
| SafeSight YOLOv8s | 0,69 | 0,70 | **0,52** | 0,07 | 204 @256 | Apache-2.0 |

Presisi pada confidence 0,5 (runtime): helm 0,87, rompi 0,85 (Hansung); sepatu 0,75 (SafeSight @256).

## Keputusan

- `models/ppe_helmet_vest.pt` = Hansung-Cho YOLOv8n (sha256 `2419700b…0760f`): helm + rompi.
- `models/ppe_boots.pt` = SafeSight YOLOv8s (sha256 `31ef3ca0…03533`): hanya kelas sepatu,
  dijalankan maks. 1x per detik pada bagian kaki saja.
- Model lama praktis **tidak mendeteksi helm/sepatu sama sekali** di data ini (hanya kacamata
  dan sarung tangan), jadi selama ini helm dan rompi sebenarnya berjalan dari deteksi warna.

## Keterbatasan yang jujur

- Kelas **"tanpa helm" / "tanpa sepatu" lemah di semua model** (AP50 ≤ 0,13). Sistem karena itu
  memutuskan "tidak pakai" dari *tidak adanya* helm/rompi pada wilayah tubuh yang terlihat jelas
  beberapa frame berturut-turut (debounce di tracker), bukan dari satu deteksi negatif.
- Sepatu: recall ±0,5. Kaki sering tidak terlihat (terpotong frame / terhalang), dan itu
  dilaporkan BELUM PASTI, bukan "tidak pakai".
- Data uji = foto proyek konstruksi. **Bengkel kita belum diuji.** Fine-tune dengan ±200 foto
  dari kamera Pico (helm/rompi/sepatu bengkel sendiri, pencahayaan sendiri) adalah langkah
  terpenting berikutnya sebelum production.
