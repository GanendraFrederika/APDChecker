> Superseding operator clarification (11 October): user physically unplugged /
> replugged during the preceding sequence. Do NOT label earlier uptime changes
> or ADB offline state as unsolicited reboot/fault. New 120 s idle + 300 s camera
> tests completed with ADB connected. Historical logs/conditional recovery steps
> below are retained; no proof of long-term USB/power stability or fault cause.
> Current status: PRODUCTION_PROGRESS.md.

# Pemeriksaan koneksi Pico berikutnya â€” kamera tetap OFF

## Bukti saat ini

11 Oktober 2026 sekitar 08:21 WIB reconnect fisik memulihkan ADB. Preview bounded
45 s berhenti otomatis. Saat audit idle sesudahnya, sekitar 08:26:03 WIB, host
ADB mencatat `connection terminated: read failed`; terakhir uptime 290,93 s dan
SoC 40,445 C. Windows masih melihat composite/ADB/RNDIS dengan problem code 0.
Restart ADB host satu kali menghasilkan offline; trace CNXN belum mendapat
balasan. Suhu itu BUKAN pengukuran sekarang. Belum ada log board setelah fault.

Hampir lima menit uptime tidak membuktikan timer tertentu. Script boot backup
mencakup auto-reboot hanya bila test file ada, tetapi proses inventory tidak
menunjukkan test reboot berjalan. Ada `luckfox_switch_rgb_resolution`; keberadaan
itu bukan bukti penyebab. Perlu periksa executable/config/log, bukan kill acak.
BOS header error 31 dan PnP OK juga bukan bukti tunggal driver/kabel/power sehat.

## Urutan uji secara diawasi

1. Catat apakah operator mencabut kabel, konektor longgar atau PC sleep sekitar
   waktu fault. Jangan menyimpulkan ini terjadi jika operator belum konfirmasi.
2. Kamera terakhir OFF terkonfirmasi. Lepaskan power dengan aman; jangan cabut
   FPC saat board hidup. Gunakan **port USB lain dulu dengan kabel yang sama**,
   langsung ke PC, tanpa hub; jangan ubah firmware/power plan bersamaan.
3. Setelah koneksi pulih: identity, boot_id/uptime, idle flag, thermal/mem,
   sensor/USB/kernel/syslog; **tanpa kamera/NPU**. Simpan script boot USB yang
   lengkap, udev rules, descriptor/runtime-PM status, config/test reboot flags,
   dan binary/helper resolution-switch secara read-only untuk diperiksa di host.
4. Jika USB ulang gagal, uji kabel **data** lain dengan port yang sama. Variabel
   satu-satu. Kabel charge-only tidak cukup. Board harus ditenagai VBUS 5 V sesuai
   dokumentasi, BUKAN Uno 3.3 V/GPIO. Tanpa multimeter tidak bisa memverifikasi
   tegangan/drop/current melalui label atau temperatur saja.
5. Log board sesudah fault paling berguna lewat jalur independen. RNDIS board
   terakhir 172.32.0.93/16, host Ethernet 2 APIPA 169.254.x.x: tidak satu subnet.
   Secondary host IP/route hanya dengan rencana port isolasi dan rollback,
   jangan mengubah Wi-Fi/default gateway atau membuka telnet/ADB di LAN.
   ADB TCP bukan solusi jika hanya tersambung melalui ADB USB yang sudah putus.
   UART serial debug memerlukan adapter 3.3 V dan pinout pasti, bukan Uno TX 5 V.
6. Jika tidak ada jalur kedua, collector lokal RAM-bounded boleh dipertimbangkan
   dengan durasi otomatis dan process identity/rollback yang diuji terlebih dulu;
   belum dibuat/dipasang di sesi ini. RAM Mini B terbatas, jangan daemon/log
   unlimited atau core dump flash. Jangan auto-reboot agar fault evidence hilang.
7. Baru ulang preview singkat setelah idle stabil. Uji casing/NPU soak terpisah.

Tidak mengganti driver USB, menonaktifkan power saving global, reset PnP hardware,
memasang service/kernel/firmware, atau mengganti runtime saat fault belum dipahami.

Evidence: `debug/reconnect/host-usb-20261011T082836/`,
`debug/thermal-audit/20261011T012507332574Z/`.
