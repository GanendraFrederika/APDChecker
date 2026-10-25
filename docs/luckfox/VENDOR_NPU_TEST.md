# Shipped vendor NPU test: evidence and limits

11 October 2026. **Not APD inference; not production acceptance.**

## Why this test exists

Camera-only streaming does not exercise the RV1103 NPU. The board already ships
`rkipc`, `librockiva.so`, `librknnmrt.so` and vendor detector files. We used that
installed path to observe genuine NPU hardware activity without replacing the OS,
firmware, libraries or adding an unverified latest-SDK model.

The audited rkipc source subtree is pinned by Git object/hash in
`debug/build-preflight/vendor-npu/sources.json`; source matching the installed
binary is **not** proven. Static installed binary strings corroborate `npu_fps`,
RockIVA API calls, small-model configuration and `/usr/lib/` path. Installed
librockiva has static version string **1.5.1, rv1106 Linux, build d0ec0292**;
installed micro-runtime string **1.4.1b9**, NPU driver **0.8.2**. String inventory
is not a query of runtime ABI/version or permission to use latest Toolkit models.

The vendor PFP file was pulled read-only: 736,112 bytes, SHA256
`4a9a0dbd8318608f8454e1f5d927d3db17cef0ca8431e0dde91a905bfb406dd1`.
It begins with RKNN magic but tensor/class/export/training/license contracts are
not validated. PFP source names person/face/pet, **not** our PPE classes; a file
named cls7 is NOT proof of our seven APD labels. No substitutions or relabeling.

## Procedure

- Explicit operator-supervised HOST script `scripts/test_luckfox_vendor_npu.py`.
- Requires Mini B serial, idle camera, no preview/vendor lock takeover.
- Byte-exact pull of persistent config before and after test.
- Changes only `enable_npu=0` to `1` in a **temporary /tmp config**. Checks shipped
  `small` model / requested NPU 3 FPS; retains sensor/encoder 10 FPS configuration.
  Recording, JPEG, IVS, secondary encoders and audio remain disabled.
- Uploads hash-checked `/tmp` variant of tested bounded local preview guard/controller.
  No boot/persistent config/runtime/model replacement; no automatic relaunch.
- Local duration <=300 s, default cutoff60 / explicit40..78 C, starts below55 C,
  checks every2 s for sensor/time/USB/log1MiB; stops only owned camera process.
  Host samples5 s and stops on low MemAvailable (<2 MiB), uptime/counter rollback.
- No HOST camera frame collection/saved images and no MCU serial or relay commands.

**Limits/side effects:** vendor rkipc initializes normal camera services, OSD,
network/NTP and storage scan even with recording disabled. It may attempt vendor
ISP light/IR-cut/PWM controls; logs show missing pwmchip export. We did not directly
issue GPIO/UART commands, but cannot claim rkipc has no such internal side effects.
The inspected video directories were empty; no image/video recording was enabled.
Temporary files/logs remain in RAM for evidence until reboot; not auto-started.

This guard is development software, NOT a fail-safe if its supervisor crashes/OOMs
or the sensor stalls at a plausible value. 78 C is the operator's **stop threshold**,
not a chip rating or guaranteed physical maximum. Sensor accuracy, polling and
shutdown delay can cause overshoot. Stopping camera/NPU does not power off Linux.

## First measured run

`debug/vendor-npu/20261011T014914Z/`:

- Requested60 s, cutoff78 C; fan nearby, no installed heatsink (operator report).
- 12 host samples, SoC41.633..46.386 C; CPU mean26.210% including stop window.
- Minimum MemAvailable8,960 kB (not free CMA/media/NPU allocation budget).
- NPU IRQ counter0 -> 1,110 and active intervals continued increasing.
- ROCKIVA_BA_Init success, runtime library mapped and VI2/NPU threads observed.
- TIME_LIMIT and CAMERA_IDLE confirmed. Persistent config byte-identical.
- PWM/light, encoder init, NTP and OSD teardown warnings preserved, not hidden.

IRQ growth proves NPU interrupt activity, **not completed detections/FPS/accuracy**.
No per-frame completion counters or APD detector outputs have been established.
There is no seven-class trained PPE model or our RK-MPI/RKNN backend deployed.

## Requirements before APD release

Required PPE/person model + float/INT8 holdout evaluation; compatible toolchain,
tensor shape/stride/quantization/anchors validated against our decoder; native
capture/RKNN cleanup + per-frame completion/freshness + observable body adapter;
actual RAM/CMA pressure and latency, enclosure/heatsink/fan/power load soak;
MCU physical commissioning/ACK/level shifting; real walking/crossing/removal/
re-wearing and fault acceptance. Current release gates remain **false**.

## Five-minute follow-up

`debug/vendor-npu/20261011T015105Z/` completed300 s, no ADB loss observed.
Max sampled 46.980 C; CPU mean 26.738%;
minimum MemAvailable 8,744 kB; IRQ delta 5,430.
Vendor init, TIME_LIMIT, idle and persistent-config byte equality confirmed.
Live snapshot CMAFree0: total/system available memory is not a claim of spare
CMA/media/RKNN budget. No completed-inference FPS or PPE class validation.
Postrun-analysis records runner revisions during the test; afterward-added checks
are not falsely attributed to the already-running imported script.
206 isolated offline tests pass for current sources.
