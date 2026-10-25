> Latest 11 October 2026: operator confirms physical USB unplug/replug; do not
> classify earlier reboot/offline snapshots as spontaneous faults. Recovered ADB,
> 120 s idle + 300 s guarded camera/RTSP completed (max sampled 45.198 C).
> Shipped vendor NPU 300 s test observed interrupt activity (max 46.980 C), NOT
> PPE inference or measured NPU FPS. User-requested test cutoff <=78 C; default
> 60 C, not a chip rating/guaranteed physical ceiling. Model/ARM/MCU gates remain.
> [Current status](PRODUCTION_PROGRESS.md) / [vendor test](VENDOR_NPU_TEST.md).
> This supersedes older numerical/status paragraphs below.

# APD Checker - Luckfox development, offline-first

Status 11 October 2026: **PPE AI remains HOST OFFLINE VALIDATION**, not a standalone deployment.
Authorized live thermal audit reduced builtin rkipc load and **verified idle boot**
after a normal reboot. A manual PC preview delivered **10 FPS**; 3/5 FPS camera
capture has NOT been achieved. See [THERMAL_AUDIT.md](THERMAL_AUDIT.md).

**Resume audit:** board reconnected and idle was verified again. A 120 s idle
window measured mean CPU 1.68%, SoC 37.475..39.851 C. A locally supervised 30 s
preview stopped automatically; a second restart/PC RTSP/manual-stop test delivered
10 FPS and ended idle. No Arduino or PPE model inference was run.

**Latest supervised USB observations completed:** operator confirmed physical
reconnects. ADB stayed connected during latest 120 s idle and 300 s camera test.
Do not infer unsolicited reboot from those earlier snapshots, or infer long-term
production stability from short tests. See USB_RECOVERY.md for historical logs.

Local preview guard checks thermal/USB/time every 2 s, refuses start >=55 C;
default stop >=60 C, explicit supervised cutoff 40..78 C. Default duration 60 s
(10..300 allowed). Invalid sensor/time/USB/log >=1 MiB stops, no automatic restart.
Sensor/poll/shutdown delay means this is not a hard physical ceiling. No power
cutoff or safety certification. Guard crash/OOM remains a development limitation.

Existing offline AI scripts still use no ADB/RTSP/camera/GPIO/serial. Separate explicit
thermal/preview HOST commands can access the board. No OS/library deletion, firmware
flashing, PPE model upload or automatic relay activation was performed. Arduino
v1.9/legacy launchers unchanged. Backups are config/script backups, not full firmware.

Further offline integration: post-NMS frame builder and geometry mapping are now
HOST-tested on 1,024 synthetic boxes; use upright view coordinates for tracking,
not inverse-rotated raw sensor coordinates. Native boundary tests and 186 isolated
regressions pass. No ARM/RK-MPI/RKNN adapter deployed. See [RV1103_BACKEND.md](RV1103_BACKEND.md).

Separate Uno APD3 candidate now builds for ATmega328P, with outputs/watchdog
commissioning disabled by default. C/Python byte parity and actual HOST C receiver
are tested; no upload/UART connection. APD3 is NOT legacy APD2 transport. See
[MCU_APD3.md](MCU_APD3.md) for draft pins/policy and exact unfinished gates.

## Workshop requirement update - 10 October 2026

The confirmed production requirement is **vest=green, shoes=yellow, helmet=red**.
All three lamps can be on for one complete person; colors identify items, not danger.
New offline per-person tracking/cache rules, visibility contract and synthetic replay
are described in WORKSHOP_TRACKING.md. The production profile is
D:\RUDY\HAIKAL\APDChecker\config\apd_workshop.json.
The current PPE model has no vest/no_vest class and is explicitly NOT READY for
that policy. The workshop tracker now has a separate bounded C port, HOST-built and matched
on 598 synthetic frames; it is NOT yet a camera/NPU board runtime.
The helmet/mask profile and per-frame/global debouncer below are retained as
**legacy model-validation/regression references**, not the workshop alarm path.

## What is implemented

- Python reference policy: associate helmet/mask evidence with an individual person;
  overlapping/ambiguous boxes and missing evidence are UNKNOWN, not SAFE.
- Conflicting positive and negative evidence for one item is UNKNOWN; an independent,
  unambiguous required-item negative can still establish VIOLATION.
- Confidence filtering, invalid boxes, configuration validation and SHA256 checks.
- Alarm indication requires >=3 fresh samples over >=1.5 seconds. Clearing requires
  >=3 samples over >=3 seconds. A >2 second inference gap resets the candidate.
- UNKNOWN retains an existing alarm indication; CAMERA_LOST/MODEL_ERROR/STARTING reset
  it and report a fault. The application is NOT a safety-rated protective system.
  Physical fault output policy must be separately agreed and validated for the site.
- Native C99 policy core under edge/luckfox, with fixed capacity and no heap allocation.
  Its session coordinator rejects duplicate frame IDs and stale inference timestamps;
  its development outputs-enabled function is hard-locked to false.
  It has no camera/NPU/serial adapter. Legacy core/session HOST tests now pass with
  verified local Zig 0.13.0. Separate workshop_tracker.c supports vest/shoes/helmet
  tracking/cache and HOST C/Python parity on 598 synthetic frames. No ARM build or
  live detector accuracy is established; all outputs remain hard-disabled.
- APD2 serial transport is reserved for future firmware and disabled by default.
  **Never probe an unknown/v1.9 board with HELLO**: the old sketch reads individual
  characters inside new protocol frames and may actuate the relay.

The legacy host-model profile uses helmet and mask as examples. Its
confirmed_by_operator remains false; the new workshop required-items/color mapping
is confirmed separately, not its accuracy/timing/hardware readiness. COMPLIANT means only the configured items have positive image evidence;
it is not a certified conclusion that all PPE is present/correctly worn.

## Offline test commands - Windows PowerShell, board unplugged

Use absolute paths; do not run python/test_arduino_serial.py or the legacy quick tests.

~~~powershell
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\test_apd_offline.py'

& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\check_apd_offline.py' --replay 'D:\RUDY\HAIKAL\APDChecker\tests\fixtures\apd_replay.jsonl'

& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\check_apd_offline.py' --image 'D:\RUDY\HAIKAL\APDChecker\docs\luckfox\captures\sc3336-20261010-165205.jpg'
~~~

The JSONL replay is **synthetic**, not a camera recording or an accuracy evaluation.
Images are local existing captures; no new picture is taken. Rotation defaults to
180 degrees in the host only. JSON/annotated JPEG/static HTML are written to
D:\RUDY\HAIKAL\APDChecker\docs\luckfox\offline-check.
A single still image can display an observation, never confirm a timed alarm.
No hardware commands are possible through this runner.

Photo inference uses two CPU models on the laptop: a generic person detector and a
PPE detector with 10 classes and no person class. This dual-model setup is a policy
validation aid, **not the recommended memory budget for Mini B**. No automatic model
download or generic-model fallback is permitted by the new detector. Only load .pt
checkpoints you trust; a hash only identifies bytes, it does not prove provenance.

## Actual RV1103 path and remaining work

Official support was checked on 10 October 2026; see
D:\RUDY\HAIKAL\APDChecker\docs\luckfox\official-support-evidence.json.
Luckfox's RK-MPI examples list camera capture for RV1103/RV1106, but their RTSP YOLOv5
example lists RV1106. Rockchip's model zoo lists RV1103 for YOLOv5, whereas its YOLOv8
object-detection support row omits RV1103. This is **not proof YOLOv8 is impossible**;
it means our existing YOLOv8 PPE checkpoint has no validated direct deployment path
here. Do not blindly install Ultralytics/Torch or flash an RV1106 image on Mini B.

1. Investigate the thermal event and establish a safe, supervised hardware test plan.
2. Confirm required PPE and collect representative, labeled evaluation images.
3. Select an explicitly RV1103-compatible, sufficiently small detector. Prefer a
   single detector including person plus required PPE/negative classes when feasible.
   A YOLOv5n-family model is one candidate for evaluation, not a promised drop-in.
   A YOLOv8 checkpoint cannot simply be renamed or re-exported as YOLOv5 weights:
   changing architecture requires compatible training/retraining and validation.
4. Prepare a Linux conversion/cross-build environment and compatible SDK; match the
   device runtime, board ABI and supported export/output layout. WSL/toolchain were
   not ready at the previous environment check. No .rknn model has been generated.
5. Implement the RK-MPI/RKNN C adapter against backend_contract.h. Return boxes in
   upright full-frame view coordinates after inverse letterbox; bind class order to a manifest;
   preserve fresh frame identity and monotonic timestamps; release every media buffer.
   Stale frames, timeout, model errors, or capacity overflow must not be SAFE.
6. HOST core and workshop C/Python parity tests now pass; still cross-compile for Mini B. Fill the manifest
   template only with measured metadata; null values and validated=false block release.
7. After hardware safety is resolved, measure real memory, latency, stream load and
   temperature under supervised conditions. Do not promise FPS from configured values.
8. Integrate MCU watchdog/ACK firmware and verified relay polarity in a separate stage.
   Prototype AI alarms must not control machinery or worker access as safety interlocks.

## Host dependency setup (not needed for policy/replay unit tests)

The offline policy/config/protocol/model-contract/tracking tests and JSONL replay use only the Python standard
library. Photo inference also requires the host-only packages. Downloads have had
read timeouts; a successful replay does not imply those packages are installed.

~~~powershell
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' -m pip install torch==2.14.1+cpu torchvision==0.29.1+cpu --index-url https://download.pytorch.org/whl/cpu
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' -m pip install -r 'D:\RUDY\HAIKAL\APDChecker\python\requirements-host.txt'
~~~

These commands are for the laptop only. No instruction here authorizes reconnecting
or installing Python packages on the overheated board.

## Sources (primary repositories)

- https://github.com/LuckfoxTECH/luckfox_pico_rkmpi_example
- https://github.com/airockchip/rknn_model_zoo

## Build HOST C core and workshop parity tests (no board access)

~~~powershell
& 'D:\RUDY\HAIKAL\APDChecker\.venv\Scripts\python.exe' 'D:\RUDY\HAIKAL\APDChecker\scripts\check_native_core.py' --zig '.tools/ziglang-0.13.0/ziglang/zig.exe' --workshop
~~~

This script exits 2 when no host compiler exists. It never downloads a toolchain or
connects to Luckfox. A passing host policy test is not an ARM ABI/NPU/camera test.
