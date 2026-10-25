# Receiver Uno APD3 - kandidat, BELUM di-upload

11 Oktober 2026. **NOT PRODUCTION READY.** Sketch lama
`arduino/apd_receiver/apd_receiver.ino` v1.9 tidak diubah. Sketch baru terpisah:
`arduino/apd_receiver_v3/`. Tidak membuka COM, upload, UART atau GPIO pada pekerjaan ini.

## Implementasi yang ditambahkan

- C receiver bounded tanpa heap, Arduino wrapper nonblocking, Python dan C encoder.
- APD3 **berbeda dari APD2 legacy host transport**. Jangan hubungkan `ActuatorLink`
  lama ke receiver baru; belum ada serial transport/UART/ACK coordinator produksi.
- Pesan `@payload*CRC8\n`, CRC-8 polynomial 0x07/init0. CRC bukan autentikasi.
- HELLO dengan session token delapan hex uppercase nonzero selalu reset evidence.
  Token hanya mencegah campuran sesi tak sengaja, tidak menahan penyerang/replay
  berbahaya. Rencana serial point-to-point, bukan endpoint jaringan terbuka.
- Seq 1..65535, forward half-range; frame ID uint32 baru, forward half-range
  (wrap diperbolehkan). DATA duplikat/mundur/CRC invalid atau capacity overflow
  membuang evidence/session. Jangan retry identical DATA; gunakan HELLO reset
  eksplisit setelah error. Transport ACK timeout/recovery belum diimplementasi.
- Timeout evidence **1.500 ms**; H/heartbeat tidak memperpanjang TTL DATA.
  Inter-byte dan keseluruhan frame dibatasi **250 ms**; slow-drip tidak bisa
  mempertahankan frame tertunda tanpa batas. Pastikan baud/latency nyata nanti.
- Tiga state+source: `P` PRESENT/FRESH, `C` PRESENT/CACHED, `N` ABSENT/FRESH,
  `D` ABSENT/CACHED, `U` UNKNOWN. Urutan selalu vest/shoes/helmet.
- Satu target per pesan: bukan OR antar pekerja. No-target/fault mengirim UUU dan
  no alarm. Candidate alarm di codec hanya untuk target dengan fresh negative;
  bukan `alarm_candidate` global milik orang lain. Target ambigu ditolak encoder:
  jangan mengirim frame yang gagal encode; transport wajib fault/stop + timeout.

Wire grammar (contoh payload; CRC wajib dihasilkan encoder, bukan diketik manual):

```text
seq,HELLO,SESSION
seq,DATA,SESSION,frame_id,observation,track_id_hex16,states3,alarm0or1
seq,H,SESSION
seq,STOP,SESSION
seq,ACK,command,READY|FAULT|IDLE
```

Observation: STARTING/NO_PERSON/UNKNOWN/COMPLIANT/VIOLATION/CAMERA_LOST/MODEL_ERROR.
HELLO ACK READY hanya berarti parser siap, **bukan** model/camera/hardware siap.
H ACK FAULT bila belum ada DATA. Fault DATA ACK FAULT diterima sebagai status fault,
bukan harus disamakan dengan error CRC/invalid parse. STOP menghapus session.

## Output fisik masih draft dan terkunci OFF

`APD_INDICATORS_COMMISSIONED=0`, `APD_ALARM_COMMISSIONED=0`,
`APD_WATCHDOG_BOOTLOADER_VERIFIED=0` adalah default source/build.
Jangan membuka gate hanya karena compilation/tests hijau.

| Pin draft Uno | Fungsi |
|---|---|
| D4 | LED rompi hijau + resistor seri |
| D5 | LED sepatu kuning + resistor seri |
| D6 | LED helm merah + resistor seri |
| D13 | Fault/starting LED bawaan |
| D10 | Relay amplifier, hanya setelah polaritas diuji |
| D9 | Sinyal audio, interface amplifier wajib diperiksa |
| D0/D1 | Hardware UART, berbagi dengan USB serial Uno |

P/C steady on; N/D off; U slow blink 1 Hz **hanya saat target ada**.
Fault LED 2 Hz; tidak ada target semua item off. Ini **usulan**, bukan pola yang
sudah disetujui pengguna. Candidate alarm 750 ms maksimum dan 10 s cooldown
(global konservatif), berhenti saat fault/STOP/no candidate/target berubah.
Ini berbeda dengan alarm terus-menerus v1.9: perlu kalibrasi bengkel dan persetujuan.
Firmware baru belum punya servo patrol/RTC/DS3231/power scheduling. D11 tidak
digunakan. Jangan klaim menggantikan semua fitur legacy atau jadwal tidur Pico.

**Disconnect relay/amplifier dan servo saat pengujian awal.** Default D10/D9
INPUT tanpa pull-up; input relay floating tidak menjamin OFF. Saat commissioning
perlu resistor eksternal OFF-state yang sesuai active-low/high dan uji reset,
bootloader, USB connect, input loss, timeout. GPIO output latch di-set OFF sebelum
pinMode OUTPUT hanya pada build alarm yang polaritasnya telah disetujui.

Uno TX 5 V tidak boleh langsung ke RX Luckfox 3,3 V. Gunakan level shifter/buffer
sesuai direction/speed dan common ground. Verifikasi UART Pico yang bebas konflik
console dan pinmux; belum ditentukan. Jangan power Pico dari Uno 3,3 V/GPIO.
LED kecil perlu resistor sesuai Vf/arus; lampu daya perlu transistor/driver terpisah.
Audio amplifier input bukan otomatis cocok sinyal tone 5 V: coupling/attenuation
sesuai datasheet dan wiring audio harus diverifikasi. Speaker TPA3110 BTL tidak
boleh sembarang disambung ke GND sistem; periksa datasheet terminal speaker.

## Watchdog dan batas keselamatan

Watchdog AVR candidate 2 s masih terkunci sampai bootloader diverifikasi. Early
`.init3` clears MCUSR/disables watchdog before constructors, tetapi tidak dapat
memperbaiki bootloader yang reset-loop ketika watchdog tetap aktif. Alarm gate
memerlukan watchdog+indicator gates. Verifikasi boot/reboot/watchdog expiry nyata
serta OFF pull hardware. Software fault means no alarm, bukan sistem safety-rated.

## Bukti build dan tes saat ini

- Portable Arduino CLI 1.5.1 archive SHA256 diverifikasi dari release metadata;
  core arduino:avr 1.8.8 + GCC 7.3.0-atmel3.6.1-arduino7 di workspace `.tools`.
- Default Uno build PASS: **6.404 B flash, 657 B global RAM**, sisa 1.391 B untuk
  local/stack. Bukan pengukuran peak stack/hardware stability.
- Compile-only alarm branches active-high/low PASS: **7.256 B flash, 678 B globals**.
  Binary ini **JANGAN UPLOAD**; hanya syntax/branch compile dengan gate override.
- Gate alarm tanpa verification sengaja diuji gagal compile.
- HOST actual C receiver: **263 byte streams** termasuk corruption/overflow,
  freshness/CRC/session, timeout, slow-drip, target change, pulse/cooldown.
- 598 synthetic tracker frames sekarang juga membandingkan byte encoder C/Python
  dan acceptance receiver C (atau penolakan explicit ambiguous target).
- Semua tests masih HOST/synthetic, bukan live UART/AVR timing atau akurasi AI.

Evidence: `debug/native-tests-20261011-mcu.log`, `debug/arduino-v3-build.log`,
`debug/arduino-v3-compile-only-active-{high,low}.log`, `debug/arduino-v3-gate-rejection.log`.
Source `edge/luckfox/mcu_frame.*`, `python/apd_runtime/mcu_protocol.py` tidak bisa
membuka port/actuate sendiri; backend/sender produksi masih diperlukan.

Build default saja (tidak upload):

```powershell
& .\.tools\arduino-cli-1.5.1\arduino-cli.exe compile --fqbn arduino:avr:uno --warnings all --config-file .tools/arduino-cli-1.5.1/arduino-cli.yaml --output-dir docs/luckfox/debug/arduino-v3-build arduino/apd_receiver_v3
```

## Commissioning berikutnya

1. Operator confirms pin/wiring, LED current, fault/unknown display, multi-target
   selection and alarm/cooldown. Keep relay/servo disconnected first.
2. Inspect bootloader + physical board, then explicitly approved upload via USB
   of reviewed candidate with outputs still disabled; verify readback/boot/silence.
3. Test LED-only stage, invalid frames/timeout/reset under observation. No APD3
   HELLO before actual sketch replacement confirmed out-of-band.
4. Validate level shifting and UART ownership. Build bounded ACK/recovery sender,
   no auto-rearm/retry stale evidence. Exercise unplug/camera/model/CPU faults.
5. Only after model/thermal/site gates, test relay with isolated dummy load and
   correct hardware OFF pull, then amplifier/audio appropriately. Not access control
   or machinery protective interlock; retain worker PPE checks independently.
