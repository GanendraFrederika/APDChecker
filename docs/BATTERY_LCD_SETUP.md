# LCD dan indikator cabang baterai (2026-10-18)

## Status

Implementasi di receiver legacy; bukan firmware APD3. Belum di-upload dalam perubahan ini.
Pengujian host dan kompilasi Uno tidak membuktikan wiring, akurasi sensor, atau kapasitas baterai.

- Boot selama 2 detik: baris 1 Hello World, baris 2 Inisialisasi...
- Sesudahnya: baris 1 CCTV Siap!, baris 2 Baterai: --% secara default.
- CCTV Siap! hanya berarti firmware MCU berjalan, BUKAN konfirmasi kamera/AI/sistem APD aman.
- Tidak membaca SMPS/A2, tidak mencoba menebak sumber daya aktif.
- Relay D10, audio D9, LED alarm D8, servo pan D11 dan protokol lama tetap.

## Aktivasi bertahap

1. Biarkan BATTERY_SENSE_ENABLED=false sampai jalur ukur sudah diperiksa secara fisik.
   Software tidak bisa memastikan bahwa A1 mengambang atau bahwa titik ukur bukan bus gabungan.
2. Jangan hubungkan positif baterai langsung ke A1. Pastikan ada pembagi tegangan,
   referensi ground pada sisi terlindung yang benar, dan tidak ada bypass proteksi BMS/shunt.
   Tinjau juga kemungkinan backfeed lewat A1 ketika MCU mati tetapi baterai masih terhubung.
   Dokumen ini tidak mengesahkan keseluruhan jalur daya/charging.
3. Cocokkan BATTERY_R_TOP_OHMS dan BATTERY_R_BOTTOM_OHMS dengan resistor terpasang.
   Nilai contoh firmware 33k/10k bukan bukti resistor itu sudah dipasang.
   Cocokkan BATTERY_ADC_REFERENCE_MV dengan AVcc terukur. Ini referensi DEFAULT Uno;
   firmware tidak mengubah analogReference(). Jangan menyuplai tegangan ke AREF sembarangan.
4. Setelah aman, aktifkan BATTERY_SENSE_ENABLED=true; biarkan BATTERY_PERCENT_ENABLED=false.
   Layar menampilkan tegangan dengan persen --. Bandingkan dengan multimeter di cabang baterai
   pada beberapa tegangan/beban sebelum percaya angka di layar.
5. Hanya bila perkiraan linear memang disetujui, aktifkan BATTERY_PERCENT_ENABLED=true.
   Layar menandai angka dengan ~. Endpoint contoh 9.90 V=0% dan 12.60 V=100% adalah
   skala demonstrasi 3S Li-ion, bukan kurva SoC sel hasil pengukuran dan bukan kapasitas/mAh.
   Untuk hasil layak pakai, karakterisasikan sel/pack atau gunakan fuel gauge yang sesuai.
   Jangan menjadikan 11.3 V sebagai 100% karena itu setelan SMPS.

## Cara kerja dan batasan

- Satu analogRead(A1) setiap minimal 50 ms, rata-rata 16 sampel valid sebelum publikasi.
  Tidak ada delay(), loop menunggu ADC, atau sampling catch-up beruntun.
  analogRead dan transaksi I2C sendiri tetap panggilan sinkron; bukan jaminan hard real-time.
- ADC nol/saturasi atau tegangan di luar jendela contoh 9.0-12.8 V menghasilkan UNKNOWN,
  menghapus rata-rata parsial, dan memerlukan 16 sampel valid baru sebelum pulih.
  Jendela ini bukan pengganti batas proteksi BMS dan tidak mendeteksi semua kesalahan kabel.
- Baris baterai diperbarui maksimal sekali per detik dan hanya jika teks berubah.
  Angka invalid ditampilkan --%, bukan dipaksa menjadi 0%/100% atau mempertahankan persen lama.
- LCD tidak terdeteksi saat boot: tidak ada penulisan LCD lanjutan; receiver tetap berjalan.
- Persentase tidak membedakan charging/discharging dan tidak mengukur energi tersisa sebenarnya.
- Jangan menganggap pembacaan atau tanda CCTV Siap! sebagai izin commissioning aktuator.

## Validasi ulang lokal (tidak membuka port serial)

Gunakan Python di .venv/Scripts/python.exe untuk menjalankan unittest discovery pada
 tests/test_apd_receiver_firmware.py. Kompilasi lewat Arduino CLI lokal dengan konfigurasi
 .tools/arduino-cli-1.5.1/arduino-cli.yaml dan FQBN arduino:avr:uno.

Tes mencakup konfigurasi default, tegangan saja, estimasi persen, invalid/pulih,
LCD tidak ada, serta regresi relay/audio, serial dan urutan patroli.
Kompilasi varian sense+persen aktif menggunakan salinan staging; source utama tetap default OFF.

## Hasil validasi 18 Oktober 2026

- 29 tes host lulus; tidak membuka serial.
- Kompilasi Uno default: flash 13,312/32,256 byte; global SRAM 870/2,048 byte.
- Kompilasi Uno sense+persen aktif: flash 13,926/32,256 byte; global SRAM 902/2,048 byte.
- Source utama tetap sense=false dan percent=false. Tidak ada upload, pengujian aktuator,
  pembacaan baterai fisik, atau konfirmasi akurasi sensor dalam perubahan ini.
- Git tidak dapat memvalidasi diff/status: perintah git status melaporkan not a git repository.
  Salinan sumber sebelum perubahan disimpan di .tools/backups/battery-lcd-20261018-1792314757009.
