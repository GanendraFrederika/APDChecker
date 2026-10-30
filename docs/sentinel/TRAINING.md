# Melatih model APD sendiri: langkah lengkap

Tujuan: satu model kecil yang mengenali **helm, rompi, sepatu, orang** di bengkel kita,
termasuk dari dinding 2,5 m dengan orang 4-5 m jauhnya.

## 0. Kenapa perlu

Model sekarang dilatih dengan foto proyek konstruksi luar negeri. Helm, rompi, cahaya dan
sudut kamera di bengkel kita berbeda. Dari dinding 2,5 m, orang di 5 m tingginya hanya
±250 px, helm ±45 px, sepatu ±40×18 px di gambar yang dianalisis. Model harus pernah
melihat contoh sekecil itu, dari atas, di tempat kita.

## 1. Rekam foto (±1 jam, butuh 2-3 orang)

1. Pasang kamera di posisi akhir (atau setinggi mungkin, ±2,5 m, menunduk ±15-25°).
2. Jalankan `jalankan-sentinel.bat`.
3. Di jendela lain: `.venv\Scripts\python.exe scripts\collect_workshop.py --minutes 20 --every 1.5`
4. Variasikan, masing-masing beberapa kali:
   - jarak 2, 3, 4, 5, 6 m; berdiri, berjalan, membungkuk, menoleh
   - **lengkap**, tanpa helm, tanpa rompi, tanpa sepatu safety (pakai sandal/sneakers), tanpa semua
   - helm warna lain, rompi warna lain, topi biasa / kaus oranye (supaya tidak tertipu)
   - pagi, siang, malam (lampu), dekat jendela (silau)
   - 1 orang, 2 orang, 3 orang saling menutupi
5. Target: **300-500 foto** dengan orang, plus ±50 foto ruangan kosong (`--all`).

## 2. Perbaiki label (±2-3 jam untuk 400 foto)

Foto sudah punya label saran dari AI di `datasets/workshop/labels/` (format YOLO).
Kelas: `0 helmet`, `1 vest`, `2 shoes`, `3 person`.

1. Buka https://www.makesense.ai → *Get Started* → *Object Detection*.
2. Upload semua foto dari `datasets/workshop/images/`.
3. *Create labels list*: ketik `helmet`, `vest`, `shoes`, `person` (urutan ini persis).
4. *Actions → Import Annotations → YOLO*: pilih semua file `.txt` dari `datasets/workshop/labels/`
   dan `classes.txt`.
5. Periksa setiap foto: hapus kotak salah, tambah yang terlewat. Aturan:
   - kotak **helm** hanya helm (bukan seluruh kepala); topi biasa **tidak** dilabeli
   - kotak **rompi** seluruh rompi yang terlihat; kaus oranye **tidak** dilabeli
   - **sepatu** satu kotak per sepatu safety; sandal/sneakers **tidak** dilabeli
   - **person** seluruh badan yang terlihat
6. *Actions → Export Annotations → YOLO* → zip berisi `.txt`. Ganti isi
   `datasets/workshop/labels/` dengan hasil ekspor ini.

## 3. Latih (pilih satu)

**A. Google Colab (disarankan, ±30 menit):**
1. Zip folder `datasets/workshop` (isi: `images/`, `labels/`) → `workshop.zip`.
2. Buka `training/train_ppe_colab.ipynb` di https://colab.research.google.com (*File → Upload notebook*).
3. *Runtime → Change runtime type → T4 GPU*, lalu *Runtime → Run all*.
4. Saat diminta, upload `workshop.zip`. Di akhir, `ppe_project.pt` terunduh otomatis.

**B. Laptop ini (±8 jam, semalaman):**
`.venv\Scripts\python.exe scripts\train_ppe.py --epochs 30 --imgsz 416`

## 4. Uji dan pasang

1. Taruh `ppe_project.pt` di `models/`.
2. Bandingkan dengan model sekarang (angka AP50 lebih tinggi = lebih baik):
   `.venv\Scripts\python.exe scripts\eval_ppe.py --data datasets\ppe-project --split test models\ppe_project.pt models\ppe_helmet_vest.pt`
3. Uji live di bengkel. Kalau lebih buruk, hapus `models/ppe_project.pt` (sistem kembali ke model lama).

## 5. Untuk standalone

Model yang sama dikonversi ke `.rknn`: lihat `docs/sentinel/STANDALONE_PICO.md`.
