# APDChecker â€” production work in progress

11 October 2026. **NOT PRODUCTION READY.** Keep MCU relay/serial disabled.

## Done and measured in this continuation

- Pico Mini B identity + idle/ISP state verified; 120 s idle CPU mean 1.68%,
  SoC 37.5..39.9 C. Not equilibrium, ambient/power/enclosure measurement.
- Local bounded preview supervisor deployed with byte-exact backup and checksums.
  30 s timer auto-stop verified, then restart + PC RTSP 10 FPS + manual-stop verified.
- No kernel/OS/driver deletion, frequency/voltage edits, firmware flash or GPIO/UART.
- Earlier offline regression: **186 passing**. Shell simulations are not real fault injections.
- Workshop C port source added with fixed 8 track/64 equipment capacity and no heap.
  Vest/shoes/helmet mapping; TTL cache, visibility gate, opposing evidence invalidation,
  conflict/ambiguity clearing, temporary geometric tracking, fresh negative confirmation,
  stale-frame tick and outputs hard-disabled. Separate from legacy policy/session core.
  HOST-built with verified local Zig 0.13.0, all warnings treated as errors.
  ws_tracker HOST sizeof=1,096 bytes, not total function stack/buffers/board RAM.
- **598-frame** C/Python synthetic parity passed: replay/demo/cross-person/conflict
  plus 512 deterministic stress frames. Legacy core/session C tests also pass.
  Evidence: debug/native-tests-20261011.log. No ARM build or model accuracy claim.

## Further offline work in this continuation

- Pure C post-NMS frame builder added; explicit seven-class label map, actual
  resize/padding and upright-view coordinates. Raw inverse rotation is overlays
  only: tracking body zones require upright head/torso/feet orientation.
- **1,024 synthetic geometry vectors HOST PASS**, plus builder/tracker integration
  tests for label order, overflow, invalid input, padding, visibility filtering,
  negative confirmation and re-wear. Additional native boundary suite passes.
- Null tracker input now invalidates evidence/report rather than leaving stale
  positive output. No ARM/camera/NPU/MCU adapter deployed.
- Rockchip RV1103 YOLOv5 reference source pinned by commit/hash. Its COCO-80 decoder
  and demo lifecycle are NOT ready for our seven-class model or production cleanup.
  See [RV1103_BACKEND.md](RV1103_BACKEND.md).
- Latest regression evidence: `debug/offline-tests-20261011-backend.log` and
  `debug/native-tests-20261011-backend.log`. Synthetic tests are not real accuracy.

## MCU continuation - HOST/compile only, not uploaded

- Separate APD3 Uno receiver candidate added; v1.9 retained unchanged. Three item
  indicator draft, bounded parser/session/freshness, ACK, alarm pulse/cooldown,
  partial/whole-line timeout. Hardware commissioning gates default OFF.
- C/Python report encoder compared on 598 synthetic tracker frames and actual
  C receiver acceptance/rejection; additional 263 corruption/time/target byte
  streams HOST PASS. No serial transport or UART/pinmux access performed.
- AVR Uno default compile PASS: 6,404 B flash, 657 B globals. Compile-only relay
  active-low/high branch PASS: 7,256 B flash, 678 B globals; MUST NOT upload those
  gate-override binaries. Gate rejection test works. Not stack/timing/hardware proof.
- Portable Arduino CLI/core installed only under workspace .tools with archive
  hash evidence. Legacy Uno sketch, relay and servo untouched.
- Physical display/selection/alarm policy, watchdog/bootloader/polarity and voltage
  shifting remain uncommissioned. See [MCU_APD3.md](MCU_APD3.md).

## Latest supervised hardware tests (11 October, 08:37 onward WIB)

Operator confirms physical unplug/replug during the preceding observations.
The earlier uptime change/offline snapshot is NOT evidence of unsolicited reboot
or failure. ADB recovered; new boot ID and read-only USB/key/helper logs archived.
No speculative helper kill, driver, host power-policy or firmware changes.
A subsequent 120 s idle audit completed: 12 samples, 38.069..39.851 C,
CPU busy mean 1.932%. This is an observation window, not equilibrium.

User explicitly requested **78 C test stop threshold**. Default preview cutoff
remains 60 C, start refusal remains >=55 C. Explicit cutoff range 40..78 C;
local sensor/time/USB/log checks every 2 s and 10..300 s duration unchanged.
This is NOT a chip rating or a guaranteed physical ceiling: sensor accuracy,
polling, shutdown latency and continued board heat can cause overshoot. Invalid
sensor/time/USB also stops; no restart. Guard crash/OOM is not hardware fail-safe.

**300 s camera + HOST RTSP test completed** using the operator-reported nearby
fan, no installed heatsink yet. 31 samples: max 45.198 C, mean 43.760 C,
CPU mean 20.484% including startup/stop and HOST audit. Available RAM minimum
9,448 kB. PC received 2,743 frames at 2304x1296, later delivery windows 10 FPS;
not a sensor/NPU FPS measurement. No saved images, PPE/NPU inference or MCU.
Local TIME_LIMIT stop and CAMERA_IDLE confirmed, ADB stayed connected throughout.
Evidence: `debug/supervised-camera/20261011T014207Z/`.

Read-only runtime inventory: ELF32 ARM EABI5 hard-float, uClibc 1.0.31,
NPU driver 0.8.2, librknnmrt static string **1.4.1b9**. Latest SDK conversion
compatibility is NOT presumed. No runtime replacement or ARM probe uploaded.
See `debug/reconnect/20261011T012148Z/runtime-summary.json`.

**60 s shipped vendor RockIVA NPU smoke test completed**: requested NPU 3 FPS,
10 FPS sensor/encoder config; max sampled 46.386 C, CPU mean 26.210%.
NPU interrupt counter advanced by 1,110 and ROCKIVA_BA_Init success was logged;
inference completion/FPS and APD accuracy are NOT established. Persistent
/userdata/rkipc.ini is byte-identical before/after. Config/guard/log used /tmp;
no model or runtime replacement. TIME_LIMIT + idle confirmed. Firmware logs
include PWM/light, encoder startup, NTP and OSD teardown warnings; not a clean
production backend. See [VENDOR_NPU_TEST.md](VENDOR_NPU_TEST.md).
Evidence: `debug/vendor-npu/20261011T014914Z/`.

Historical evidence retained: `debug/reconnect/host-usb-20261011T082836/`,
`debug/thermal-audit/20261011T012507332574Z/`. Do not reinterpret physical
operator reconnect as an autonomous fault; these short tests still do not prove
continuous connection, electrical power quality or enclosure stability.

## Longer vendor NPU observation completed (08:51-08:56 WIB)

300 s bounded shipped vendor test: **46.980 C maximum**,
CPU mean **26.738%**, minimum MemAvailable
**8,744 kB**. NPU interrupt counter advanced by
**5,430**, with increasing active intervals; vendor init
success logged. Not completed-inference FPS, APD accuracy or enclosure equilibrium.
Persistent preview config byte-identical; TIME_LIMIT + CAMERA_IDLE confirmed,
no observed ADB disconnect. No installed heatsink yet; operator-reported fan.
Evidence: `debug/vendor-npu/20261011T015105Z/` and postrun-analysis.json.
CMA free was observed zero during a live snapshot: MemAvailable does not prove
media/NPU headroom. Vendor internal light/PWM/OSD/network/storage side effects and
teardown warnings remain; see VENDOR_NPU_TEST.md. Not our production backend.

Latest isolated HOST regression **206 tests PASS** including partial-start cleanup,
forward cleanup, bounded command validation and vendor profile/IRQ parsing.
Evidence: `debug/offline-tests-20261011-supervised-final.log`. No real MCU upload.

## Decoder continuation — HOST only

Portable seven-class optimized YOLOv5 post-sigmoid INT8 NCHW grid decoder added;
explicit model anchors/affine quantization/row-channel strides, strict bounds,
stable score sorting, class-aware NMS, overflow invalidation and UNKNOWN person
visibility. This is NOT YOLOv8 compatibility or an RV1103 adapter. Caller-owned
workspace (HOST 6,664 B) not total stack/ARM/media/RKNN memory. The dataset,
seven-class weights/export contract, real-model INT8 holdout parity and RKNN
lifecycle remain missing. See [GRID_DECODER.md](GRID_DECODER.md).

Grid-stage offline suite **191 tests PASS**; native suite adds **256 synthetic tensor
C/Python differential vectors**, malformed/capacity cases and builder/tracker
integration. Tests do not establish real detector accuracy or NPU performance.

## Release gates â€” none may be bypassed

1. **Connection/power/thermal**: continuous idle/camera observations now passed;
   distinguish operator unplugging from spontaneous faults using logs and timestamps;
   separately test stable 5 V supply, actual enclosure/heatsink/fan and sustained NPU.
   Mini B must not be supplied from Uno 3.3 V or GPIO. OS idle is not power-off.
2. **Dataset & model**: current PPE checkpoint lacks vest/no_vest/person; static
   metadata evidence in debug/build-preflight/host-model-preflight.json. Never map
   mask to vest or use general YOLO as PPE fallback. Define safety-shoe vs shoe
   requirements, valid helmet/vest wear and observable/occluded body regions.
   Collect consented representative labeled clips/images (walking, occlusion,
   crossing, removal/re-wearing, lighting). Keep evaluation people/clips separate
   from training/calibration; licensing/accuracy/false-alarm metrics required.
3. **Conversion/build**: verified RV1103-compatible network/output and installed
   micro-runtime version/ABI; compatible Linux conversion environment and SDK.
   HOST Zig compiler is for policy tests only, NOT a uClibc RK-MPI toolchain.
   No .rknn file/backend or production ARM binary yet. Vendor RV1103-specific
   model-zoo source/CMake is reference, not proof our trained model runs.
4. **Native integration**: RK-MPI frame capture + RKNN, upright-view inverse
   letterbox and calibrated rotation, validated visibility adapter, fresh capture IDs/monotonic
   timestamps, no buffer leaks, memory/latency/resource/thermal measurements.
   Detector missing item never means explicit absence by itself.
5. **MCU/site policy**: existing Uno v1.9 char parser is incompatible with framed
   APD2 and may actuate from digits. Do NOT send HELLO/test frames. New firmware,
   pin plan, voltage levels, relay polarity, watchdog/ACK, UNKNOWN display and
   multi-person selection need separately tested commissioning. No alarms driving
   machines/worker access as safety-rated protection.
6. **Acceptance**: representative per-item accuracy + false alarms + missed cases,
   measured traversal timing and max inference gaps, unplug/reboot/model/camera
   faults, cache expiry/removal/re-wear, crossing, long enclosure soak, rollback.
   Only measured accepted artifacts can enable deployment; templates remain false.

## Controls

```powershell
# Explicit status/stop:
& .\.venv\Scripts\python.exe scripts/control_luckfox_preview.py status --serial 2be53eb6debe9106
& .\.venv\Scripts\python.exe scripts/control_luckfox_preview.py stop --serial 2be53eb6debe9106
# Short supervised session, after checking idle/cooling:
& .\.venv\Scripts\python.exe scripts/control_luckfox_preview.py start --serial 2be53eb6debe9106 --duration 30
& .\.venv\Scripts\python.exe scripts/test_apd_offline.py
# Explicit HOST compiler, no board access:
& .\.venv\Scripts\python.exe scripts/check_native_core.py --zig .tools/ziglang-0.13.0/ziglang/zig.exe --workshop
```

Guard start refuses stale locks/unmanaged rkipc; do not blindly remove its directory
or signal arbitrary PIDs. Runtime logs bounded in RAM; boot remains idle. Practical
55 C start / 60 C default / explicit <=78 C gates are development choices, not chip damage/safety specifications.
No automatic relaunch after fault. Camera auto-stop != board power-off or Linux sleep.

Backup: debug/preview-guard-20261011T003557Z/; manifest is config/scripts/evidence
only, not full NAND/OS backup. Previous unguarded preview controller is retained
for forensic rollback, but restoring it removes new protections.

## RKNN lifecycle candidate continuation - HOST only

Added open/query/strict logical-and-native tensor validation, bounded requested IO
allocation, padded RGB row copy, synchronous run/freshness checks and once-only
reverse cleanup. Invalid/late/model errors clear output and FAULT until close.
No camera/media backend, model, matching SDK ABI, real inference or MCU deployment.
See [RKNN_ENGINE_CANDIDATE.md](RKNN_ENGINE_CANDIDATE.md).

Pinned SDK reference header/libs were acquired read-only on HOST with Git blob and
SHA256 provenance. Reference library hashes differ from board; not proof of ABI
incompatibility or a matching header. No runtime replacements or firmware changes.

Corrected the stale config disconnect blocker: operator reconnect is not an
autonomous fault. Short tests passed; sustained PPE/enclosure/supply acceptance
still blocks production. Actuators and deployment remain disabled. Read-only
audit CLI now also accepts explicit 78 C, with mocked exact-boundary tests; this
CLI logs/exits only, unlike the board-local preview workload stop guard.

Latest native engine HOST test PASS: **18** open-operation fault injections,
**27** version/tensor/allocation metadata faults, **10** run/freshness faults,
plus duplicate-ID/gate/cleanup/input-padding/decoder cases. Existing synthetic
tracker/geometry/grid/MCU suites still pass. Offline suite **208 tests PASS**.
Evidence: debug/native-tests-20261011-rknn-engine.log and
debug/offline-tests-20261011-rknn-engine.log.

Final read-only snapshot: 40.445 C, camera idle, same boot ID,
guard hashes match HOST, MemAvailable 15,380 kB and CMAFree 0 kB. Timestamped only;
no ongoing temperature monitoring and no new camera/NPU workload this continuation.
Snapshot evidence: debug/rknn-engine-continuation/20261011T021054Z/.


## 2026-10-11 continuation -- checklist and motion-aware camera view

User deferred migration and resumed APD development, adding a future two-servo
pan/tilt requirement. Inventory and acceptance checklist are now in
CHECKLIST_PRODUCTION.md; motion constraints in PAN_TILT_PLAN.md.

Implemented exposure-view epoch and moving/settling suppression in Python/C
tracking, with explicit between-frame invalidation and monotonic IDs/timestamps.
Any changed view starts fresh evidence/tracks; old queued-view frames rejected.
Metadata defaults remain fixed-view compatibility only. The C frame builder
resets metadata; future capture adapter must restore saved exposure metadata.
No cross-pose identity/re-ID or camera motor protocol has been implemented.

HOST CameraMotionGate sequences move/ACK/settle/reacquire and fails closed on
stale/duplicate ACK, timeout or invalid clock. No servo angles/GPIO/serial, no
position-feedback proof, and development dwell/timeout not physically calibrated.
Fixed camera remains the first deployment plan. New pan/tilt integration blocker
is recorded in apd_workshop.json; actuators/deployment remain OFF.

Verification this continuation:
- Offline suite: 229 tests PASS, including 21 new camera-view/motion cases.
- Native HOST suite PASS: 614 Python/C synthetic tracker frames; 1024 box
  transform vectors; boundary tests including motion/held alarm invalidation;
  263 MCU byte streams; 256 grid tensors; existing mocked RKNN lifecycle tests.
- First offline run exposed a pre-existing fake-camera test race: harness accepted
  a live launching shell as the camera before its own marker was written. Test
  adapter now waits for runtime marker before returning an identity token,
  matching the real adapter's readiness intent. Board guard was NOT changed.
- No new device access, camera/NPU workload, UART/relay/servo command, firmware
  upload, source SVG/model/OS edit, runtime replacement or production acceptance.

Evidence:
- debug/offline-tests-20261011-camera-view.log
- debug/native-tests-20261011-camera-view.log

Actual PPE model (vest contract), RV1103 camera/backend/SDK ABI, visibility,
physical MCU/audio/power/thermal and site acceptance remain release blockers.
These HOST passes are logic evidence, not detector accuracy or field readiness.


## 2026-10-11 -- operator correction and supervised debugging setup

Operator confirmed legacy relay + TPA3110 + speaker already function. Reviewed
legacy source: relay D10, tone D9, alarm LED D8, servo D11; left working sketch
unchanged. This is operator-tested basic functionality, not new live verification
or acceptance of candidate APD3/watchdog/power. Corrected checklist statements
that implied basic audio had not been built. Flagged legacy D8 conflict with
proposed pan/tilt pin reservation and automatic 60-second patrol during fixed
camera accuracy testing. Source also shows a pattern-duration index offset;
intended versus actual sustained tone cadence is documented, not silently fixed.

Added DEBUGGING_SETUP.md with operator/component prerequisites, assistant
automation boundaries, camera-only versus genuine PPE inference readiness,
independent human annotation, scenario/evidence requirements and a staged session.
Planned next Saturday means 2026-10-17 WIB, not guaranteed production completion.
Two-servo calibration, power/UPS/brownout and final fan/enclosure soak deferred
as requested. Real vest-capable model and RV1103 capture/RKNN/visibility backend
remain blockers; camera preview and vendor NPU smoke tests do not resolve them.

Added 12 NOT_RUN scenarios and empty session/accuracy templates. Added a HOST-only
CSV diagnostic scorer: per-item confusion matrix, visible false alarm/false SAFE,
UNKNOWN-inclusive violation recall and coverage, optional capture-to-decision
latency. Empty evidence rejected; report overwrite refused. UNOBSERVABLE cached
results distinguished from fresh assertions for manual TTL/view review. No mAP,
event-level acceptance, real-person accuracy, ID switch scoring or independent
ground truth generation claimed. New tests are synthetic scorer tests only.

Verification: 243 isolated offline tests PASS (previous 229 + 14 scorer tests).
CLI smoke test PASS on temporary synthetic CSV, including overwrite and empty
report refusal; scenario ids/status/gates checked. Evidence:
- debug/offline-tests-20261011-debug-plan.log
- debug/accuracy-scorer-cli-20261011.log

No ADB/COM connection, new camera/NPU workload, servo/relay commands, firmware
upload, SVG/Blender edit, runtime/OS replacement or physical test this continuation.
No thermal monitor running in background. Candidate output/deployment gates remain
unchanged and OFF. Native C tests were not rerun for these documentation/scorer
changes; prior camera-view native evidence remains separately recorded.
