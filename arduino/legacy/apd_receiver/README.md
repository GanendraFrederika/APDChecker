# APD Receiver legacy v2.1: ServoEasing, LCD dan debug indikator

Firmware uji manual ini mempertahankan UART legacy 9600 baud, relay D10,
audio D9, LED alarm D8, servo pan D11, dan patroli 60 detik.
Bukan receiver APD3 dan bukan firmware production yang sudah dikomisioning.

## Pin map terbaru (menggantikan rencana pin lama untuk sketch ini)

| Pin | Fungsi | Implementasi saat ini |
| --- | --- | --- |
| D0 / D1 | UART Luckfox RX / TX | Serial 9600 baud, parser legacy |
| D2 | DS18B20 Arduino | Dicadangkan; belum ada pembacaan sensor |
| D3 | DS18B20 Pico | Dicadangkan; belum ada pembacaan sensor |
| D4 | Merah / ind_helm_m | Debug atau alarm |
| D5 | MOSFET kipas kamera dan Pico | Dicadangkan; belum ada kontrol kipas |
| D6 | MOSFET kipas Arduino | Dicadangkan; belum ada kontrol kipas |
| D7 | Servo naik-turun | Dicadangkan; tidak di-attach/digerakkan |
| D8 | LED alarm | Pola audio legacy |
| D9 | Audio input TPA3110 | tone()/noTone() legacy |
| D10 | Relay daya TPA3110 | Polaritas konfigurasi lama dipertahankan |
| D11 | Servo kanan-kiri | ServoEasing cubic-in-out; patrol enam waypoint |
| D12 | Hijau / ind_rompi_h | Debug |
| D13 | Kosong | LED builtin tidak dikendalikan lagi |
| A0 | Kuning / ind_sepatu_k | Output digital, bukan input tegangan |
| A1-A3 | Kosong | Tidak dipakai |
| A4 | LCD SDA | I2C Wire |
| A5 | LCD SCL | I2C Wire |

## LCD

Asumsi: LCD 16x2 memakai backpack **PCF8574 I2C** dengan pemetaan default
library. LCD paralel tanpa backpack tidak cocok dengan sketch ini.
Gunakan library **LiquidCrystal_PCF8574 by Matthias Hertel**, versi uji 2.3.0,
**Servo**, versi uji 1.3.0, dan **ServoEasing by Armin Joachimsmeyer 3.6.0**.
Wire tersedia dalam core Arduino AVR.

LCD hanya menampilkan `Hello World` pada baris pertama; baris kedua kosong.
Tulisan debug dihapus, tetapi animasi lampu tetap ON.
Tidak ada clear/print LCD berulang di loop.
Alamat awal `LCD_I2C_ADDRESS = 0x27` adalah asumsi, belum hasil tes perangkat.
Jika backpack memiliki alamat lain (misalnya 0x3F), sesuaikan konstanta itu.
Jika probe alamat gagal, UART mencetak
`WARN:LCD_NOT_FOUND_CHECK_ADDRESS_AND_WIRING` dan firmware tetap berjalan.
Pada core yang mendukungnya, timeout Wire disetel 25 ms dengan reset bus.

## Lampu debug dan alarm

- `DEBUG_TRAFFIC_LIGHT = true` secara default.
- `void debugTrafficLight()` dipanggil setiap loop.
- Normal: merah 1 detik -> kuning 1 detik -> hijau 1 detik -> ulang.
- Pelanggaran/alarm: debug normal dijeda; merah 100 ms ON / 100 ms OFF,
  kuning dan hijau OFF. Berlaku sepanjang status alarm termasuk jeda sirene.
- Setelah alarm dibatalkan: debug mulai lagi dari merah selama 1 detik.
- Ubah `DEBUG_TRAFFIC_LIGHT` menjadi `false` untuk mematikan animasi normal.
  Merah tetap berkedip cepat saat alarm; selain itu ketiga indikator OFF.
- Warna debug **bukan** hasil pemeriksaan helm, sepatu, atau rompi.
  Parser legacy belum membawa status terpisah per item.
- Menonaktifkan debug saja tidak menjadikan firmware siap production.

Semua timer lampu, servo kembali ke tengah, dan tes relay memakai millis().
Tidak ada delay()/while gerakan servo yang menghambat pemrosesan UART.
Urutan nada legacy tidak dirombak. Tes relay tidak boleh mengalahkan alarm:
R diabaikan selama alarm, alarm membatalkan timeout tes relay, dan S/0
langsung mematikan relay sebelum servo kembali ke tengah.

## ServoEasing dan urutan patrol

- Servo pan D11 memakai **EASE_CUBIC_IN_OUT**: pelan saat mulai, lebih cepat di
  tengah, lalu melambat sebelum berhenti/berganti arah. Bukan bounce/overshoot.
- Urutan lengkap: **90 -> 0 -> 130 -> 0 -> 130 -> 90**.
- Tidak lagi menulis 0 secara mendadak ketika patrol dimulai.
- Jika T diterima saat servo terkunci di sudut lain, servo terlebih dahulu
  bergerak halus ke 90, lalu mengikuti urutan yang sama.
- Kecepatan rata-rata patrol: **PATROL_SPEED_DPS = 22 derajat/detik**.
  Kembali ke tengah setelah S/0: **RETURN_SPEED_DPS = 30 derajat/detik**.
  Nilai lebih kecil memperlambat gerakan. Kecepatan puncak cubic lebih tinggi
  dari nilai rata-rata ini. Tidak ada jeda tambahan pada ujung lintasan.
- Memakai setEaseTo() dan update() di loop tiap 20 ms, bukan easeTo() blocking
  atau interrupt easing tambahan. Library Servo tetap menghasilkan pulsa servo.
- Penyelesaian memakai isMoving(), bukan pembulatan sudut read(). Kurva tidak
  dipotong hanya karena pembacaan derajat sudah membulat ke target.
- Alarm 1/A memanggil stop() sebelum update servo; pulsa terakhir tetap ditahan,
  servo tetap attach, dan semua waypoint berikutnya dibatalkan.
- S/0 mematikan relay/audio lebih dahulu lalu easing kembali ke 90.
  S/0 berulang tidak me-reset kurva. T berulang selama patrol juga tidak
  me-reset urutan. T tetap merupakan override manual legacy, termasuk dari alarm.
- Timer idle 60 detik dimulai setelah easing kembali ke 90 selesai.
- Sudut serial adalah posisi perintah, bukan hasil pengukuran encoder.
- D7 tilt tetap dicadangkan; belum di-attach atau digerakkan.

Library diinstal ke direktori user Arduino CLI lokal proyek, bukan otomatis
ke direktori library Arduino IDE global. Jika membuka sketch di IDE lain,
install ServoEasing 3.6.0, Servo 1.3.0, dan LiquidCrystal_PCF8574 2.3.0 di sana.
Perintah install/compile dari root proyek (PowerShell):

~~~powershell
$cli = '.tools/arduino-cli-1.5.1/arduino-cli.exe'
$cfg = '.tools/arduino-cli-1.5.1/arduino-cli.yaml'
& $cli --config-file $cfg lib install 'ServoEasing@3.6.0'
& $cli --config-file $cfg compile --fqbn arduino:avr:uno --warnings all --build-path .tools/build/apd_receiver_servoeasing arduino/apd_receiver
~~~

Periksa jangkauan mekanik 0-130 agar tidak menabrak stopper. Gunakan supply
servo eksternal sesuai spesifikasi servo dan ground sinyal bersama; jangan
mengandalkan pin 5 V Uno untuk menanggung beban motor/kamera. Easing software
belum membuktikan gerak fisik mulus: supply drop, beban, dan servo masih perlu
penilaian langsung. Setelah upload/reset servo menuju posisi awal 90 dan
patrol otomatis mulai setelah 60 detik; kosongkan area gerak terlebih dahulu.

## Uji manual setelah wiring diverifikasi

1. Pasang LED dengan resistor seri masing-masing; A0 sekarang untuk LED kuning.
2. Pastikan LCD memakai backpack I2C dan supply sesuai modulnya, ground bersama,
   SDA ke A4 dan SCL ke A5. Jangan upload dengan rangkaian daya yang belum aman.
3. Compile untuk Arduino Uno, lalu lakukan upload secara manual jika siap.
4. Periksa tulisan LCD dan urutan tiga warna. Tidak perlu mengaktifkan TPA3110
   untuk tes awal LCD/lampu; lepas daya aktuator saat hanya menguji tampilan.
5. Pada UART legacy 9600 baud, setelah aktuator aman diuji:
   - 1 / A: alarm, relay ON, servo mengunci, merah cepat.
   - 0 / S: relay dan suara OFF, servo kembali 90, debug dilanjutkan.
   - T / t: patrol 90 -> 0 -> 130 -> 0 -> 130 -> 90; lampu tetap berputar normal.
   - R / r: relay ON 3 detik nonblocking jika tidak sedang alarm.
6. Hindari dua pengirim UART bersamaan (Luckfox dan Serial Monitor).
   Jangan kirim frame APD3 ke parser ini.

## Validasi offline

Compile dengan Arduino CLI: fqbn `arduino:avr:uno`.
Uji host (mock I/O, tidak membuka COM):

~~~powershell
python -m unittest discover -s tests -p test_apd_receiver_firmware.py -v
~~~

Uji host menjalankan sketch asli melalui mock Arduino/Wire/LCD/ServoEasing,
termasuk batas 1 detik, prioritas alarm, millis wraparound, LCD tidak ada,
debug OFF, urutan enam waypoint, model kurva cubic, perintah berulang, dan
perintah serial saat servo patrol/kembali/tes relay. Mock ServoEasing adalah
model perilaku, bukan library asli; compile AVR memakai library asli 3.6.0.
Compile, uji host, dan upload bukan bukti gerak fisik servo sudah mulus atau
perangkat sudah memenuhi penerimaan production.
