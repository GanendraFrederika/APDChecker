# Luckfox thermal audit - 11 October 2026

## Latest continuation: guarded preview tested, communication still unresolved

This section supersedes the historical final-state paragraphs below.
- Serial/identity reverified; idle flag and no rkipc, ISP count zero at resume.
- 120 s idle: CPU mean **1.679%**, SoC mean **38.343 C**, range **37.475..39.851 C**.
- On-board `apd-preview-session.sh` and replacement `apd-previewctl.sh` backed up,
  syntax checked, SHA256 verified after push/pull; no boot/config/firmware change.
- Guard polls every 2 s, start <55 C, stop >=60 C/invalid sensor/USB not configured/
  monotonic-clock fault/maximum 10..300 s/log >=1 MiB. Default 60 s. Development only.
- 30 s local timer test: automatic TIME_LIMIT, rkipc absent, ISP interrupts stopped,
  max sampled SoC **43.415 C**. No PC camera frames saved or PPE inference.
- Restart test: 80 PC-decoded frames in 8 s (**10 FPS**), TERM stop succeeded,
  no remaining RTSP port; decoder gave one initial reference-frame warning.
- Later ADB vanished while last confirmed camera state was idle. Windows USB
  composite/ADB/RNDIS still present; last reading **38.663 C**, NOT current.
  HOST ADB reconnect did not recover; server restart produced offline state.
  Active board tests ended. No root-cause diagnosis from these short observations.
- Guard is NOT a production watchdog: if USB remains configured but ADB fails,
  only bounded duration is assured by design. Its death/OOM cannot guarantee stop;
  no hardware power switch. Never deliberately heat the board to prove a threshold.
- Host guard simulations cover thermal/sensor loss, USB loss, clock fault, time/log
  bounds, no takeover and lock refusal. Those are not live fault-injection evidence.

Evidence: `debug/preview-guard-20261011T003557Z/` and
`debug/thermal-audit/20261011T003054224074Z/`. Current host tests: 175 passing.
Old sections below retain historical experiments, not current device state.

## Historical status: idle boot VERIFIED; recurrent USB loss UNRESOLVED

After physical USB reconnect, ADB recovered and `/proc/device-tree/model` verified
Luckfox Pico Mini B (serial `2be53eb6debe9106`). USB `Nexus_4/occam` is a misleading
firmware descriptor, not the actual model. No UART/GPIO/Arduino/relay was operated.

### Applied and verified

- **10 FPS preview profile**: ISP/src/dst 10 FPS, GOP 20, one 2304x1296 H.265 stream.
  Demo NPU, audio/VQE, IVS, JPEG and sub/third encoders OFF; recording already OFF.
  Geometry, buffers and AIQ preserved. This is NOT our PPE model/inference.
- ISP frame deltas before reboot: **9.96 FPS**. After reboot, PC RTSP preview
  advertised and delivered **10.0 FPS**, 121 decoded frames after a three-second
  startup discard. No pictures saved. A startup decoder reference-frame warning
  occurred; this short preview is not a long-term stream quality/AI accuracy test.
- **Idle boot guard DEPLOYED** in `/oem/usr/bin/RkLunch.sh`, controlled by
  `/userdata/apd-camera-idle`. Only the builtin rkipc launch is skipped; original
  driver, network and config initialization is preserved. Manual preview start
  does not remove the flag, so subsequent boots remain idle.
- Normal reboot verified: ADB recovered, `CAMERA_IDLE`, `BOOT_MODE_IDLE`, ISP
  interrupts zero, no RTSP listener, no rkipc, 10 FPS INI retained.
- No OS, libraries, drivers or firmware partitions deleted. No swap, CPU governor,
  undervolting, firmware flashing, nightly RTC schedule or PPE deployment performed.

### Measured results

| Condition | Mean CPU busy | Mean SoC temperature | Window |
|---|---:|---:|---:|
| Historical builtin demo | ~70% | 52.36 C | ~120s |
| Camera10 before reboot, RTSP bind failed | 15.50% | 43.78 C | ~180s |
| Verified idle after reboot | 2.96% | 39.50 C | ~120s |

Idle final ~60s: CPU 2.55%, SoC 39.11 C. Sampling itself consumes CPU. Sequential
warmup histories differed; NOT a matched/equilibrium experiment or power measurement.
No ambient sensor/thermometer/power measurement was available. SoC is not camera,
regulator or enclosure temperature. 164 isolated offline tests pass, including
config patches, guarded boot-launch changes and host preview control.

### Why the old FPS settings were misleading

Only setting NPU FPS throttled builtin inference, not the camera/ISP. Encoder online
mode logged `online not support fps setting`: destination-only 5 FPS still delivered
about 25. Changing ISP/src rate reduced actual frames to around 10, but requests 3
and 5 did not achieve those rates. Current config honestly requests **10**. Do not
promise below-10 capture without supported SDK/driver investigation and measurement.
PPE inference could later run less frequently than capture; it is not deployed yet.

### Restart pitfall identified

USB `udhcpc` spawned by vendor boot inherited RTSP/control listening sockets from
rkipc. After graceful camera stop, the listener inode still belonged to DHCP PID
424, so a new preview had `Address already in use` and no RTSP, despite camera
frames/encoder working. Evidence: `thermal-recovery-20261011/socket-inheritance.txt`.
DHCP was NOT killed. Normal reboot with idle guard cleared those inherited sockets;
manual preview then worked. Previewctl now surfaces known RTSP-bind failure instead
of treating a live PID as proof of stream health. No diagnosis of USB loss follows
from this separate socket issue.

### Final hardware state: communication lost again

After successful post-reboot preview, USB/ADB disappeared around **07:10 WIB**.
The following audit saved one sample, **43.415 C**, then `device not found`.
Subsequent Windows checks no longer showed VID_2207. This differs from the first
incident, when Windows still enumerated USB. No high-temperature cutoff was reached.
The cause is UNKNOWN; do not infer overheating, wrong supply voltage, thermal
shutdown or damaged hardware from these observations.

**Final camera stop is unconfirmed**: communication was lost while preview was
running. If the board still receives power, treat the camera as potentially active.
User was asked to remove USB power if connected, without needing to reconnect yet.
No further active tests are running. **Next boot is verified to be idle.**
This is development idle, not hardware power-off/sleep or functioning PPE monitoring.

### Disk/storage findings

Raw NAND/MTD/UBI, rootfs 95% full (~3.3 MB free), OEM 78%, userdata nearly empty.
No swap. Main logical/uncompressed sizes: Python stdlib ~55 MB, Samba libs ~15 MB.
`du` logical sizes are not directly comparable to compressed UBIFS `df` space.
No large stray recordings/core dumps demonstrated. Recording folders empty.
`/var/log` points to RAM `/tmp`; observed logs were tens of KB. Idle files mainly
consume capacity, not continuous CPU. Active writes/logging can add CPU/I/O, but
raw MTD counters did not quantify UBI writes: absent diskstats means UNMEASURED,
not zero I/O. Deleting Linux/Python/libraries is not a justified cooling fix.

### Backups and current control

PC byte-exact `adb pull` backups with SHA256 manifests:
- `debug/thermal-backup-20261011/`: pre-audit INI and boot scripts.
- `debug/thermal-recovery-20261011/`: reconnect state, staged/verified edits, evidence.

**NOT a full OS/firmware backup**; do not delete/flash firmware based on these.
Board original script: `/oem/usr/bin/RkLunch.sh.apd-original`.
Original SHA256: `b6d58f74c8d6219472083718c7bda45b35250ecfb1e1cd4e628ca465e7ca763a`.
Guard SHA256: `e4c9a2187ddf907a4480650844f0168ac2c9acc981187c7ed40905ff67c9807e`.
Original INI: `/userdata/rkipc.ini.thermal-original`; pre-10 INI:
`/userdata/rkipc.ini.apd-before10`. rkipc reformats/saves its INI at stop, so hash
changes alone are not a host edit; compare parsed options and save stopped versions.

On NEXT supervised connection verify identity/status first. Do not immediately start
camera stress tests. Explicit HOST control (no Arduino protocols):

```powershell
& '.\.venv\Scripts\python.exe' '.\scripts\control_luckfox_preview.py' status --serial 2be53eb6debe9106
& '.\.venv\Scripts\python.exe' '.\scripts\control_luckfox_preview.py' stop --serial 2be53eb6debe9106
# Start only after USB stability/cooling checks:
& '.\.venv\Scripts\python.exe' '.\scripts\control_luckfox_preview.py' start --serial 2be53eb6debe9106
```

Preview start checks <65 C but has NO ongoing thermal watchdog. Read-only audit
70 C cutoff stops HOST polling, NOT board power/application; it is a practical
supervised threshold, not a manufacturer's safety/damage limit. Supervise tests.
Never use old Arduino serial quick-tests/launchers accidentally.

```powershell
& '.\.venv\Scripts\python.exe' '.\scripts\audit_luckfox_thermal.py' audit --serial 2be53eb6debe9106 --duration 120 --interval 5
# Explicit offline candidate; no upload:
& '.\.venv\Scripts\python.exe' '.\scripts\audit_luckfox_thermal.py' candidate --source '.\docs\luckfox\debug\thermal-recovery-20261011\camera10.after-stop.ini' --fps 10 --output '.\camera10.UNAPPLIED.ini'
```

Vendor adbd supports only PTY shell, not exec-out or shell -T. Quote fixed scripts
for DEVICE shell without host shell; strip PTY CRs for text, use adb pull for exact
binary backups. Preview control checks remote status marker. Mocks do not prove
future USB stability. RTSP via ADB forward worked after reboot:
`adb -s 2be53eb6debe9106 forward tcp:18554 tcp:554`, then
`rtsp://127.0.0.1:18554/live/0`. Direct RNDIS access timed out earlier.

### Rollback

Verify board identity and **stop preview first**. Restore original vendor boot:

```powershell
& '.\platform-tools\adb.exe' -s 2be53eb6debe9106 push '.\docs\luckfox\debug\thermal-recovery-20261011\RkLunch.original.sh' /oem/usr/bin/RkLunch.sh
& '.\platform-tools\adb.exe' -s 2be53eb6debe9106 shell 'chmod 755 /oem/usr/bin/RkLunch.sh; chown 1005:1005 /oem/usr/bin/RkLunch.sh; sync'
```

Original script ignores idle flag and starts builtin camera next boot with current
lightweight INI. Full-heavy INI rollback is separate and increases load/heat:

```powershell
& '.\platform-tools\adb.exe' -s 2be53eb6debe9106 push '.\docs\luckfox\debug\thermal-backup-20261011\rkipc.ini' /userdata/rkipc.ini
```

Do not repeatedly relaunch the full driver loader for manual preview restarts.

### Evidence and remaining work

- `debug/thermal-recovery-comparison.json` and `thermal-audit-status.json`.
- `debug/thermal-audit/20261011T000403391183Z/`: preboot camera10.
- `debug/thermal-audit/20261011T000746265600Z/`: verified reboot idle.
- `debug/thermal-audit/20261011T001030613141Z/`: interrupted post-preview audit.
- `debug/thermal-recovery-stream10-postboot.log`: 10 FPS PC delivery.
- `debug/thermal-recovery-20261011/isp-10fps-preboot.json`: ISP delta.
- Historical raw experiments/comparison remain in `debug/thermal-audit/` and
  `thermal-comparison-20261011.json`. Tests: `debug/thermal-audit-tests.log`.

Remaining: supervised USB stability investigation (cable/connector/host port/supply,
recover logs if available), confirm final camera stop, retest manual start/stop
without inherited ports only after stability. No further stress tests now. Longer
heatsink/fan/enclosure/PPE inference testing is separate before production readiness.

Pico clock resets to 1970: nightly time schedule needs reliable time/RTC. Arduino
Uno GPIO/3.3 V cannot supply Pico; keep USB/VBUS supply and proper load switch,
shutdown/RTC and UART level/backfeeding design separate. OS removal is not required.
