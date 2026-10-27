# Sentinel Link Protocol v1.1 (SLP/1.1) — KONTRAK

Brain (laptop sekarang, Luckfox nanti) <-> MCU (Arduino Uno, `arduino/apd_sentinel`).
File ini satu-satunya sumber kebenaran. `python/sentinel/protocol.py` dan firmware
(`sentinel_core.*`) WAJIB identik byte-per-byte. Golden vectors:
`tests/fixtures/sentinel_vectors.json` (kedua sisi diuji terhadap file itu).

## 1. Framing

- UART 115200 8N1 (USB-serial Uno sekarang; UART Luckfox + level shifter nanti).
- Frame: `'$' BODY '*' HH '\n'`. Satu `'\r'` tepat sebelum `'\n'` ditoleransi.
- BODY: 1..80 byte, tiap byte 0x20..0x7E, tidak boleh `'$'` atau `'*'`. Field dipisah `','`.
- HH: CRC-8 atas byte BODY saja. Poly 0x07, init 0x00, MSB-first, tanpa refleksi,
  tanpa XOR akhir (= `apd_runtime.protocol.crc8`). Dua digit hex HURUF BESAR.
  Hex huruf kecil = error format.
- Integer brain->MCU: regex `-?[0-9]{1,5}` lalu cek rentang. Integer MCU->brain
  boleh sampai 10 digit (ms uint32). Token: tepat 8 char `[0-9A-F]`, bukan `00000000`.
- Receiver: `'$'` selalu memulai frame baru (frame parsial dibuang). BODY > 80 ->
  buang sampai `'\n'`, laporkan `ERR,OVF`. Jeda antar-byte > 100 ms di dalam frame -> buang.
  Byte di luar frame diabaikan, KECUALI di MCU baris yang diawali `'#'` = console
  manusia (FIRMWARE_SPEC §9).
- MCU membatasi balasan `ERR` maksimal 4 frame per detik.

## 2. Satuan sudut

Semua sudut di link = **deci-degree sudut servo absolut** seperti `Servo.write()`
(0..1800 = 0..180,0°). Pulsa: `us = 544 + (dd*1856 + 900) / 1800` (integer, sama
dengan peta Servo.write 544..2400 us). Pengguna mengukur batas dengan angka
`Servo.write()`, jadi angka itu dipakai langsung (90° -> 900).

Arah fisik (kanan/atas) TIDAK dikodekan di link. Brain menyimpan `pan_sign`/`tilt_sign`
(+1 = sudut servo naik membuat kamera menoleh KANAN / mendongak ATAS).

## 3. Brain -> MCU

| Body | Aturan |
|---|---|
| `HELLO,<tok>` | Mulai/ulang sesi. Simpan token, lupakan seq terakhir, matikan alarm, servo tetap di posisinya. Balas `READY` lalu `LIM`. Dalam mode CAL -> `ACK,HELLO,ERR,MODE`. |
| `S,<tok>,<seq>,<mode>,<pan>,<tilt>,<spd>,<items>,<alarm>,<ppl>,<viol>,<trk>` | State + setpoint, 10 Hz (minimal 4 Hz). §3.1 |
| `ENV,<tok>,<soc_dC>` | Suhu SoC Luckfox deci-°C, -400..1500. Dipakai kontrol kipas P selama 10 s. Balas tidak ada. |
| `PING,<n>` | n 0..65535. Balas `PONG,<n>,<ms>`. Berlaku tanpa sesi dan saat CAL. |
| `GETLIM` | Balas `LIM,...`. |
| `CAL,<0/1>` | Masuk/keluar kalibrasi. Masuk ditolak `ACK,CAL,ERR,BUSY` saat alarm berbunyi. Masuk CAL mengakhiri sesi (token dihapus), alarm/relay OFF. `ACK,CAL,OK,<0/1>` |
| `JOG,<P/T>,<dd>` | Hanya CAL. 0..1800, TIDAK di-clamp ke batas lunak (untuk mencari batas), bergerak dengan profil kecepatan CAL. `ACK,JOG,OK,<dd>` |
| `SET,P,<MIN/MAX/HOME>,<dd>` | Hanya CAL. 0..1800. Hasil akhir harus lolos validasi zona §5, kalau tidak `ACK,SET,ERR,RANGE` (nilai lama tetap). `ACK,SET,OK,<axis><key>` contoh `ACK,SET,OK,PMIN` |
| `SET,T,<MIN0/MIN1/MAX/MAXR/HOME>,<dd>` | Hanya CAL. MIN0 = batas bawah tilt saat pan di PMIN, MIN1 = saat pan di PMAX, MAXR = batas atas tilt saat pan di PMIN (naik linear ke MAX di PHOME). Validasi §5. |
| `SET,<P/T>,<VMAX/ACC>,<v>` | Hanya CAL. VMAX 10..600 deg/s, ACC 50..3000 deg/s². |
| `SAVE` | Hanya CAL. Simpan kalibrasi ke EEPROM, cal=1. `ACK,SAVE,OK,0` |
| `LOAD` | Muat EEPROM (kosong/CRC salah -> default). `ACK,LOAD,OK,0` atau `ACK,LOAD,ERR,BLANK` |
| `DEFAULTS` | Hanya CAL. Default ke RAM, cal=0 (belum disimpan). `ACK,DEFAULTS,OK,0` |
| `FAN,<A/P>,<duty>` | duty -1 = otomatis, 0..255 manual selama 60 s. `ACK,FAN,OK,<A/P>` |

Perintah khusus CAL di luar CAL -> `ACK,<cmd>,ERR,MODE`. Setelah SAVE/LOAD/DEFAULTS/SET
yang sukses MCU juga mengirim `LIM`.

### 3.1 Field frame `S`

| Field | Tipe / rentang | Arti |
|---|---|---|
| tok | 8 hex | harus sama dengan token sesi, kalau tidak `ERR,TOKEN` (frame diabaikan) |
| seq | 1..65535 | diterima bila pertama setelah HELLO, atau `((seq-last) & 0xFFFF)` di 1..32767; selain itu `ERR,SEQ` |
| mode | `I P A T G V S F` | I=home/idle, P=patroli (tanpa orang), A=akuisisi, T=lock+inspeksi 1 orang, G=framing grup, V=lock pelanggar, S=mencari target hilang, F=fault brain (kamera/model) |
| pan, tilt | 0..1800 | target sudut servo (dd). MCU clamp ke [MIN,MAX] (flag 0x80). |
| spd | 1..600 | kecepatan maksimum diminta deg/s; MCU pakai min(spd, VMAX sumbu) |
| items | 3 char dari `P A U -` | urutan HELM, ROMPI, SEPATU. P=terpakai A=tidak ada (terkonfirmasi) U=belum pasti/tertutup `-`=tidak ada target |
| alarm | 0/1 | 1 hanya boleh bersama mode V, selain itu `ERR,RANGE` |
| ppl, viol | 0..99 | jumlah orang terlihat / pelanggar terkonfirmasi |
| trk | 0..65535 | id track yang di-lock, 0 = tidak ada |

Jumlah field salah -> `ERR,FMT`. Kata perintah tak dikenal -> `ERR,CMD`. `S` saat CAL -> `ERR,MODE`.
Link timeout: sesi aktif dan tidak ada `S` diterima selama 1500 ms -> LINK LOST (FIRMWARE_SPEC §6).

## 4. MCU -> Brain

| Body | Arti |
|---|---|
| `READY,SENTINEL,<ver>,<tok>,<cal>` | Saat boot (tok `00000000`) dan setelah HELLO (echo tok). ver = `3.2.0`. |
| `LIM,<pMin>,<pHome>,<pMax>,<tMin0>,<tMin1>,<tHome>,<tMax>,<pVmax>,<tVmax>,<pAcc>,<tAcc>,<tMaxR>,<cal>` | Zona aman + profil gerak aktif (§5). Firmware <= 3.1 mengirim 12 field tanpa `tMaxR` (brain menganggap tMaxR = tMax). |
| `LCD,<baris0 16 char>\|<baris1 16 char>` | Cermin teks LCD 16x2 untuk preview di dashboard: saat teks berganti dan tiap 2 s. Teks bisa berisi koma; pisah di `\|` pertama. (3.2) |
| `T,<ms>,<pan>,<tilt>,<panT>,<tiltT>,<flags>,<tA>,<tP>,<fanA>,<fanP>,<vcc>,<seq>` | Telemetri tiap 50 ms (20 Hz) selalu. pan/tilt = posisi perintah saat ini (dd), panT/tiltT = target setelah clamp (dd), flags = 2 hex, tA/tP = DS18B20 deci-°C atau `NA`, fan 0..255, vcc = Vcc minimum 1 s terakhir (mV), seq = seq S terakhir diterima (0 = belum). |
| `PONG,<n>,<ms>` | balasan PING |
| `ACK,<cmd>,<OK/ERR>,<detail>` | hasil perintah |
| `ERR,<code>` | CRC FMT CMD TOKEN SEQ RANGE MODE OVF |
| `EVT,BOOT,<hh>` | sekali saat boot: MCUSR (01 PORF, 02 EXTRF, 04 BORF, 08 WDRF) |
| `EVT,LINK,<LOST/OK>` | transisi supervisi link |
| `EVT,LCD,<hh>,<A1A2/A4A5/NONE>` | hasil probe LCD saat boot (alamat 2 hex, bus) |
| `EVT,TEMP,<A/P>,<OK/ABSENT>` | transisi sensor suhu |
| `EVT,VCC,<mV>` | Vcc turun < 4500 mV (maks 1 per detik) |

Flags telemetri: 01 sesi aktif, 02 link ok, 04 alarm berbunyi, 08 relay ON,
10 servo bergerak, 20 mode CAL, 40 LCD ok, 80 setpoint di-clamp batas lunak.

## 5. Zona aman (diukur pengguna 24-10-2026, atap kanan 26-10-2026) dan default firmware

Zona = segi banyak cembung dalam sudut servo (dd):

```
PMIN <= pan <= PMAX
tmin(pan) <= tilt <= tmax(pan)
tmin(pan) = MIN0 + ceil_div((MIN1 - MIN0) * (pan - PMIN), PMAX - PMIN)
ceil_div(a, b>0) = a >= 0 ? (a + b - 1) / b : -((-a) / b)     (int32, C division)
(pembulatan ke ATAS = konservatif; firmware memakai versi float yang <= nilai ini)
tmax(pan) = pan >= PHOME ? TMAX : MAXR + (TMAX - MAXR) * (pan - PMIN) / (PHOME - PMIN)
(pembagian int32 C, pembulatan ke BAWAH = konservatif)
```

Lantai lurus + atap cekung (naik lalu datar) = zona tetap **cembung**. Itu syarat
penghalus gerak firmware: output servo adalah rata-rata berbobot pose-pose di dalam
zona, jadi pasti tetap di dalam zona.

| Kunci | Default | Arti fisik (laporan pengguna) |
|---|---|---|
| PMIN | 0 | pan mentok KANAN |
| PHOME | 900 | lurus depan |
| PMAX | 1450 | pan mentok KIRI |
| MIN0 | 1450 | batas bawah tilt saat pan mentok kanan |
| MIN1 | 1000 | batas bawah tilt saat pan mentok kiri |
| THOME | 1800 | home: lurus depan (rig sejajar orang saat development; CCTV di dinding: ±1250) |
| TMAX | 1800 | paling atas (tidak bisa naik lagi) |
| MAXR | 1700 | paling atas saat pan mentok KANAN (kabel/mekanik, 26-10-2026) |
| pVmax / tVmax | 120 / 90 deg/s | kecepatan maksimum |
| pAcc / tAcc | 300 / 200 deg/s² | akselerasi (3.2: lebih lembut, puncak arus servo lebih kecil) |

Validasi (SET/boot): semua 0..1800; PMIN < PMAX; PMIN <= PHOME <= PMAX;
MIN0 < MAXR <= TMAX; MIN1 < TMAX; tmin(PHOME) <= THOME <= TMAX; VMAX 10..600; ACC 50..3000.
EEPROM versi 4 (3.2). Data versi lama diabaikan, sehingga default di atas yang dipakai.

Clamp setpoint: pan ke [PMIN,PMAX], lalu tilt ke [tmin(pan), tmax(pan)].
Invariant gerak: posisi servo SAAT INI selalu di dalam zona, juga di tengah
gerakan: tilt bergerak dulu di dalam [tmin, tmax] pada pan sekarang, lalu pan
bergerak di dalam irisan zona pada tilt baru. Jadi:
- kamera menunduk di kiri, target di kanan bawah: tilt **naik dulu**, baru pan berputar;
- kamera di kiri atas (180°), target kanan atas: tilt **turun ke 170° dulu**, baru pan
  berputar ke kanan;
- pose lama di luar zona (mis. pose boot 0/1800 dari firmware lama): servo hanya boleh
  bergerak kembali ke arah zona, pelan (30 °/s).

Arah: brain menyimpan `pan_sign = -1` (sudut pan naik = kamera menoleh KIRI) dan
`tilt_sign = +1` (sudut tilt naik = kamera mendongak). Kalibrasi FOV otomatis
(`scripts/sentinel_calibrate.py`) mengukur tanda dan skala piksel per derajat.

## 6. SLP/1.1 (firmware 3.1.0, 26-10-2026)

Frame `S` boleh 12 field (SLP/1.0) **atau** 15 field:

```
S,<tok>,<seq>,<mode>,<pan>,<tilt>,<spd>,<items4>,<alarm>,<ppl>,<viol>,<trk>,<fx>,<fx_id>,<vox>
```

| Field | Arti |
|---|---|
| items4 | 4 char `P A U -`: HELM, ROMPI, SEPATU, SARUNG TANGAN |
| fx | `-` tidak ada, `N` angguk (iya), `H` geleng (tidak), `C` celingak-celinguk, `W` sapa |
| fx_id | 0..255; animasi diputar sekali setiap nilai ini berubah (frame diulang 10 Hz) |
| vox | 1 = suara diizinkan (sirine + nada), 0 = senyap. Frame 12 field = 1 |

Perintah baru: `VOL,<0..100>` → `ACK,VOL,OK,<v>` (volume nada/sirine, default 50).
Perintah dihapus: `LOAD` (EEPROM dimuat saat boot). Telemetri `pan/tilt` = posisi yang
benar-benar dikirim ke servo (setelah penghalus). Teks LCD normal berganti maksimal tiap 3 s.

## 7. Firmware 3.2.0 (26-10-2026)

- Atap tilt bergantung pan (`MAXR`, `LIM` 14 field, `SET,T,MAXR`), EEPROM versi 4.
- Frame `LCD,...` (cermin layar LCD untuk dashboard).
- Perbaikan supervisi link: waktu `last_s_ms` bisa sedikit LEBIH BARU dari `now` loop
  (frame diproses setelah `millis()` dibaca). Selisih unsigned membungkus menjadi ±49 hari
  dan link dianggap putus sesaat ("LINK AI PUTUS" berkedip di LCD, alarm/animasi terpotong,
  `ENV`/`FAN` manual langsung kedaluwarsa). Sekarang loop membaca jam setelah memproses
  frame, dan semua selisih waktu "sudah lewat X ms?" memakai aritmetika bertanda.
