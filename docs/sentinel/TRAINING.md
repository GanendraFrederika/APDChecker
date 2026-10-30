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

Setiap foto sudah punya **label saran dari AI** (`datasets/workshop/labels/*.txt`, format YOLO,
kelas `0 helmet`, `1 vest`, `2 shoes`, `3 person`). Tugasmu hanya **mengoreksi**, bukan menggambar
semuanya dari nol. Label yang salah lebih merusak model daripada label yang kurang, jadi teliti.

### Cara A (disarankan): alat bawaan, tanpa upload, tanpa install

1. Klik dua kali **`label-review.bat`**. Jendela "Periksa Label APD" terbuka di tengah layar,
   langsung di foto pertama yang belum diperiksa.
2. Untuk setiap foto:
   - **Kotak benar semua?** Tekan **Enter** (= "Benar, lanjut"). Foto ditandai sudah diperiksa.
   - **Kotak salah kelas?** Klik kotaknya, tekan **1** Helm / **2** Rompi / **3** Sepatu / **4** Orang.
   - **Kotak salah tempat/ukuran?** Klik lalu seret untuk geser; seret sudut putih untuk ubah ukuran.
   - **Kotak tidak perlu?** Klik, tekan **Delete**.
   - **Ada yang terlewat?** Pilih kelas (1-4), lalu seret kotak baru di area kosong.
   - Salah langkah: **Ctrl+Z**. Pindah foto: **←** / **→**.
3. Semua perubahan **langsung tersimpan** ke file label. Bisa ditutup kapan saja dan dilanjutkan
   nanti; bilah "Sudah diperiksa" menunjukkan progres.
4. Selesai kalau bilah sudah penuh (semua foto diperiksa).

### Aturan melabeli (sama untuk semua orang yang membantu)

| Kelas | Dilabeli | **Tidak** dilabeli |
|---|---|---|
| Helm | kotak pas di helm saja | topi biasa, kepala tanpa helm, helm yang tidak dipakai (di meja) |
| Rompi | seluruh rompi yang terlihat di badan | kaus/jaket oranye atau kuning biasa |
| Sepatu | satu kotak per sepatu safety | sandal, sneakers, kaki tanpa sepatu |
| Orang | seluruh badan yang terlihat | orang yang terlihat kurang dari separuh |

- Objek tertutup/terpotong **lebih dari separuh**: tidak usah dilabeli.
- Ragu? Lebih baik **tidak** dilabeli daripada dilabeli salah.
- Orang tanpa helm: **orangnya tetap dilabeli** (kelas Orang), helmnya tidak ada kotak.
  Dari situlah sistem tahu "orang ini tidak pakai helm".

### Cara B: makesense.ai (kalau mau dikerjakan di laptop lain)

1. https://www.makesense.ai → *Get Started* → upload semua foto `datasets/workshop/images/` →
   *Object Detection*.
2. *Create labels list*: `helmet`, `vest`, `shoes`, `person` (urutan ini persis).
3. *Actions → Import Annotations → YOLO*: pilih semua `.txt` dari `datasets/workshop/labels/`
   + `classes.txt`.
4. Koreksi dengan aturan di atas, lalu *Actions → Export Annotations → YOLO* dan ganti isi
   `datasets/workshop/labels/` dengan hasil ekspor.

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

Model yang sama dikonversi ke `.rknn` di VPS: lihat `docs/sentinel/VPS_RKNN.md`, lalu `docs/sentinel/STANDALONE_PICO.md`.
