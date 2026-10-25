# Smart fan APDChecker -- rencana hardware dan firmware

Diperbarui 14 Oktober 2026. Dokumen ini adalah rencana commissioning; belum
mengubah atau meng-upload `apd_receiver.ino`.

## Kesimpulan komponen Arduino

Pada Uno R3 resmi, komponen regulator dari jalur jack/VIN ke rail 5 V adalah
U1, keluarga 1117 (dokumen Arduino menyebut SPX1117M3-L-5; board clone sering
mencetak AMS1117-5.0/NCP1117ST50T3G). Itu **bukan sensor suhu** dan bukan
ATmega328P. Baca tulisan pada board untuk memastikan clone yang digunakan.

Jika Uno diberi 12 V melalui jack, regulator linear membuang daya sebagai panas.
Jika rail 5 V ter-regulasi tersedia, pilihan termal yang lebih baik adalah
memberi Uno melalui pin 5V dengan benar, tanpa USB/5V kedua yang tersambung
bersamaan. Jangan menganggap heatsink menyelesaikan suplai 12 V yang terlalu
berat.

ATmega328P mempunyai sensor suhu internal, tetapi akurasinya sekitar +/-10 C
menurut datasheet; itu tidak cocok sebagai pengaman suhu utama. Gunakan sensor
eksternal yang ditempel pada lokasi yang ingin dilindungi.

## Sensor yang disarankan

Pakai **2x DS18B20 3-wire**:

- Sensor `PICO`: ditempel pada heatsink/area SoC Rockchip Pico.
- Sensor `UNO`: ditempel pada heatsink/regulator U1 atau dekat hotspot regulator.

Keduanya bisa berbagi satu bus 1-Wire karena setiap DS18B20 mempunyai alamat
unik. Rangkaian:

```text
Arduino 5V  -------- VDD kedua sensor
Arduino GND -------- GND kedua sensor
Arduino D2 --------- DQ kedua sensor
D2 ke 5V ----------- resistor pull-up 4.7k
```

Baca alamat sensor saat commissioning, lalu simpan alamatnya sebagai `PICO`
dan `UNO`; jangan mengandalkan urutan hasil scan.

Sensor bukan pengganti sensor junction. Tempelkan dengan thermal tape/epoxy
termal tipis, jangan sampai kaki atau pad sensor membuat short. Pada regulator
SOT-223, beri isolasi jika heatsink dapat menyentuh tab regulator.

## Driver kipas

**Jangan hubungkan kipas langsung ke pin Arduino.** Pin Arduino hanya menjadi
sinyal kendali.

Untuk dua kipas DC 40x40 mm, gunakan satu kanal MOSFET low-side per kipas:

```text
supply fan +  -------- + kipas
- kipas ------------- DRAIN MOSFET
SOURCE MOSFET ------- GND supply fan
Arduino PWM --------- 100 ohm -------- GATE MOSFET
GATE ke GND --------- 10k pulldown
Arduino GND ---------- GND supply fan
```

Tambahkan kapasitor 100 uF + 100 nF dekat konektor kipas. Untuk kipas dua
kabel brushed/DC, pasang dioda flyback sesuai polaritas beban setelah tipe fan
terkonfirmasi. Jika kipas 4-kabel PC/PWM, pin PWM fan berbeda dan rangkaian ini
harus disesuaikan.

Cek label kipas terlebih dahulu:

- Kipas 5 V: pakai rail 5 V eksternal yang cukup arus; jangan membebani
  regulator Uno.
- Kipas 12 V: pakai rail 12 V yang sesuai; gate MOSFET tetap dari Arduino.

Jangan menebak tegangan atau arus stall dari ukuran 40 mm.

## L298N atau servo?

- **Servo pan/tilt:** tidak memakai L298N. Kabel signal servo langsung ke pin
  Arduino; V+ servo dari supply 5--6 V eksternal yang mampu menangani arus stall;
  GND supply servo disatukan dengan GND Arduino.
- **L298N:** adalah H-bridge untuk motor DC/stepper, bukan pengendali servo
  posisi. L298N juga bukan pilihan baik untuk kipas kecil karena rugi tegangan
  dan panasnya besar.
- **Kipas:** gunakan MOSFET logic-level. L298N hanya boleh menjadi solusi
  sementara jika tipe/tegangan/arus fan memang cocok dan panas driver diukur;
  desain utama kita tidak menggunakannya.

## Pin map yang disarankan untuk sistem gabungan

Pin map ini sengaja mempertahankan fungsi legacy relay/audio dan menyediakan dua
PWM kipas. Firmware produksi nanti perlu memakai map ini secara eksplisit.

| Pin Uno | Fungsi |
|---|---|
| D0/D1 | UART; jangan dipakai beban lain |
| D2 | Bus 1-Wire dua DS18B20 |
| D3 | Cadangan / jangan dipakai fan karena bentrok Timer2 dengan `tone()` |
| D4 | LED rompi hijau pada firmware produksi |
| D5 PWM | MOSFET kipas Pico |
| D6 PWM | MOSFET kipas Uno/regulator |
| D7 | Servo tilt/naik-turun |
| D8 | LED alarm legacy; bisa menjadi salah satu indikator setelah firmware digabung |
| D9 | Audio tone legacy, dipertahankan |
| D10 | Relay legacy, dipertahankan |
| D11 | Servo pan/kanan-kiri; saat ini servo legacy |
| D12 | LED indikator produksi yang tersisa / cadangan |
| D13 | Fault/status |
| A4/A5 | I2C DS3231 bila RTC dipakai |

V3 saat ini mendefinisikan indikator D4/D5/D6. Itu bentrok dengan D5/D6 PWM
kipas. Karena itu **jangan upload v3 apa adanya** setelah kipas dipasang.
Firmware produksi harus memindahkan mapping indikator, misalnya D4/D8/D12,
atau memindahkan PWM kipas setelah seluruh pin map disetujui.

## Aturan kecepatan kipas

Versi awal yang konservatif:

### Kipas Pico

| Suhu sensor Pico | Kecepatan kipas Pico |
|---:|---:|
| < 45 C | 35--40% minimum stabil |
| 45--52 C | 50% |
| 52--58 C | 65--75% |
| 58--62.9 C | 85--95% |
| >= 63 C | 100% |

### Kipas Arduino/regulator

| Suhu sensor Uno | Kecepatan kipas Uno |
|---:|---:|
| < 40 C | 30--40% minimum stabil |
| 40--48 C | 50% |
| 48--55 C | 70--85% |
| >= 55 C | 100% |

Gunakan hysteresis sekitar 3 C: setelah masuk full-speed pada 63 C, jangan turun
sebelum Pico berada di bawah sekitar 60 C. Terapkan moving average 3--5 sampel
dan perubahan PWM bertahap supaya kipas tidak berosilasi.

Jika sensor putus, alamat salah, atau nilai tidak valid: kedua kipas langsung
100%, D13 fault berkedip, dan status dikirim sebagai `THERMAL_SENSOR_FAULT`.
Jika Pico mencapai 70--75 C, sistem harus masuk status thermal warning/fault dan
menghentikan workload AI secara terkontrol pada sisi Pico; 78 C adalah batas stop
pengembangan yang diminta operator, bukan target kerja dan bukan rating chipset.

Sensor Arduino juga harus dapat memicu full-speed sendiri. Jangan hanya memakai
suhu Pico sebagai master, karena regulator Uno bisa panas walau Pico dingin.

## Aliran udara mekanis

- Kipas Pico mengarah melewati heatsink SoC Pico, bukan langsung ke lensa.
- Kipas Uno mengarah melewati heatsink regulator/hotspot Uno.
- Sediakan jalur masuk dan keluar udara; dua kipas yang saling berhadapan tanpa
  exhaust hanya mengaduk udara panas.
- Uji papan terbuka dahulu. Uji tabung/enclosure dan thermal soak tetap tahap
  terpisah setelah fan, heatsink dan sensor terpasang.

## Urutan commissioning

1. Pastikan tulisan tegangan/arus kedua kipas.
2. Beli/pasang 2 DS18B20, resistor 4.7k, 2 MOSFET logic-level, resistor gate
   100 ohm + 10k pulldown per gate, kapasitor rail fan dan dioda sesuai tipe fan.
3. Tes sensor D2 tanpa kipas: tampilkan dua alamat dan suhu melalui Serial.
4. Tes satu MOSFET + satu fan dengan PWM 30/50/100%; ukur apakah fan benar-benar
   start pada duty minimum.
5. Tes fan kedua terpisah.
6. Tempel sensor dan bandingkan idle/AI workload. Jangan membuat AI stress tanpa
   cutoff.
7. Baru masukkan logika fan ke firmware gabungan. Jangan mengubah firmware legacy
   yang sudah mengontrol relay/audio sebelum backup dan pin map disetujui.
8. Kalibrasi dua servo paling akhir; servo memakai supply eksternal, bukan Uno
   5V regulator dan bukan L298N.

## Status keputusan

- Keputusan: **kipas memakai MOSFET, servo langsung dari pin Arduino**.
- Pin awal: **D5 kipas Pico, D6 kipas Uno, D2 DS18B20**.
- Existing relay/audio tetap D10/D9.
- Existing servo tetap D11; servo kedua direncanakan D7.
- Belum ada perubahan source/upload karena sensor, tipe kipas, MOSFET, dan rail
  fan belum dikonfirmasi.
