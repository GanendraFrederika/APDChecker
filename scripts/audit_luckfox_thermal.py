"""Explicit HOST CLI: read-only board audit OR offline preview-config preparation.
No push, reboot, service changes, UART/GPIO, camera capture, or deletion exists here.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from apd_runtime.thermal_audit import (blocks, cpu_counters, cpu_usage,
    disk_sectors, disk_delta, temperature, summarize, preview_candidate, camera_preview_candidate)

INVENTORY = r"""
printf '@@ identity\n'; cat /proc/device-tree/model
printf '\n@@ clock\n'; date; cat /proc/uptime
printf '@@ memory\n'; cat /proc/meminfo
printf '@@ mounts\n'; cat /proc/mounts
printf '@@ space\n'; df -k
printf '@@ processes\n'; ps -o pid,ppid,args
printf '@@ boot\n'; cat /etc/inittab 2>/dev/null
for f in /etc/init.d/* /oem/usr/bin/RkLunch.sh /oem/usr/bin/RkLunch-stop.sh; do
 [ -f "$f" ] || continue
 printf '\nFILE %s\n' "$f"; head -160 "$f"
done
printf '@@ thermal_policy\n'
for z in /sys/class/thermal/thermal_zone*; do
 [ -d "$z" ] || continue
 printf '%s\n' "$z"; cat "$z/type" "$z/temp" 2>/dev/null
 for f in "$z"/trip_point_*; do [ -f "$f" ] || continue; printf '%s=' "$f"; cat "$f"; done
done
printf '@@ flash_layout\n'; cat /proc/mtd 2>/dev/null; cat /proc/partitions
printf '@@ frequency\n'
for f in /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq /sys/class/devfreq/*/cur_freq; do
 [ -f "$f" ] || continue; printf '%s=' "$f"; cat "$f"
done
printf '@@ sockets\n'; netstat -lnt 2>/dev/null
"""
SAMPLE = r"""
printf '@@ uptime\n'; cat /proc/uptime
printf '@@ thermal\n'; cat /sys/class/thermal/thermal_zone0/temp
printf '@@ stat\n'; head -1 /proc/stat
printf '@@ disk\n'; cat /proc/diskstats
printf '@@ memory\n'; grep -E '^(MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo
printf '@@ rkipc\n'; pidof rkipc 2>/dev/null || true
printf '@@ camera_pipeline\n'; head -14 /proc/rkisp-vir0 2>/dev/null || true
printf '@@ frequency\n'; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || true
printf '@@ process_cpu_ticks\n'
cat /proc/[0-9]*/stat 2>/dev/null || true
"""


def adb_output(adb, serial, script):
    # Vendor adbd only supports PTY shell, not exec-out or shell -T.
    # Quote the entire fixed script for the DEVICE shell; no host shell is used.
    # Text only: PTY inserts CR bytes. Use adb pull for byte-exact/binary backups.
    result = subprocess.run([str(adb), "-s", serial, "shell", "sh -c " + shlex.quote(script)],
                            capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout.replace(b"\r", b"")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    candidate = commands.add_parser("candidate", help="HOST ONLY: create unapplied preview profile")
    candidate.add_argument("--source", type=Path, required=True)
    candidate.add_argument("--fps", type=int, choices=(3, 5, 10), required=True)
    candidate.add_argument("--output", type=Path, required=True)
    audit = commands.add_parser("audit", help="Read-only; requires correct explicit serial")
    audit.add_argument("--serial", required=True)
    audit.add_argument("--adb", type=Path, default=ROOT / "platform-tools/adb.exe")
    audit.add_argument("--duration", type=int, default=60)
    audit.add_argument("--interval", type=int, default=5)
    audit.add_argument("--stop-at-c", type=float, default=70.0,
                       help="Supervised test cutoff, NOT a chip safety specification")
    args = parser.parse_args(argv)
    if args.mode == "candidate":
        text = args.source.read_bytes().decode("utf-8")
        result = camera_preview_candidate(text) if args.fps == 10 else preview_candidate(text, args.fps)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="") as f:
            f.write(result)
        print(f"HOST CANDIDATE ONLY: {args.output}; NPU disabled; NOT APPLIED/NOT CAMERA-VALIDATED")
        return 0
    if not 10 <= args.duration <= 600 or not 2 <= args.interval <= 30:
        parser.error("duration 10..600 seconds; interval 2..30 seconds")
    if not 40 <= args.stop_at_c <= 78:
        parser.error("supervised cutoff must be 40..78 C")
    if args.interval > args.duration:
        parser.error("interval cannot exceed duration")
    identity = adb_output(args.adb, args.serial, "cat /proc/device-tree/model\n")
    if identity.replace(b"\x00", b"").strip() != b"Luckfox Pico Mini B":
        raise RuntimeError("Wrong board identity; refusing to audit")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "docs/luckfox/debug/thermal-audit" / stamp
    out.mkdir(parents=True, exist_ok=False)
    cfg = adb_output(args.adb, args.serial, "cat /userdata/rkipc.ini\n")
    (out / "rkipc.ini.backup").write_bytes(cfg)
    samples = []
    stopped = None
    previous = None
    previous_disks = None
    previous_uptime = None
    deadline = time.monotonic() + args.duration
    try:
        while True:
            data = blocks(adb_output(args.adb, args.serial, SAMPLE).decode("utf-8", "replace"))
            temp = temperature(data["thermal"])
            uptime = float(data["uptime"].split()[0])
            if not math.isfinite(uptime) or uptime < 0:
                raise ValueError("invalid uptime")
            if previous_uptime is not None and uptime <= previous_uptime:
                raise ValueError("board reboot/uptime rollback; comparison aborted")
            counters = cpu_counters(data["stat"])
            disks = disk_sectors(data["disk"])
            row = {"host_utc": datetime.now(timezone.utc).isoformat(),
                   "uptime_seconds": uptime, "temperature_c": temp,
                   "cpu": cpu_usage(previous, counters) if previous else None,
                   "disk_io_since_previous_sample": disk_delta(previous_disks, disks) if previous_disks is not None else None,
                   "memory": data.get("memory"), "rkipc_pid": data.get("rkipc"),
                   "process_stat_raw": data.get("process_cpu_ticks"),
                   "camera_pipeline": data.get("camera_pipeline"),
                   "frequency_khz": data.get("frequency")}
            samples.append(row)
            with (out / "samples.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            print(json.dumps({k:v for k,v in row.items() if k not in ("process_stat_raw", "camera_pipeline")}), flush=True)
            previous, previous_disks, previous_uptime = counters, disks, uptime
            if temp >= args.stop_at_c:
                stopped = "SUPERVISED_CUTOFF: disconnect power/cool board; NOT auto-shutdown"
                print(stopped, file=sys.stderr)
                break
            if time.monotonic() >= deadline:
                break
            if not (out / "inventory.txt").exists():
                (out / "inventory.txt").write_bytes(adb_output(args.adb, args.serial, INVENTORY))
            time.sleep(min(args.interval, max(0, deadline-time.monotonic())))
    except (RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        stopped = str(exc) or "INTERRUPTED"
    report = {"read_only": True, "changes_applied": False,
              "serial": args.serial, "backup_sha256": hashlib.sha256(cfg).hexdigest(),
              "requested_duration_seconds": args.duration, "cutoff_c": args.stop_at_c,
              "stopped_reason": stopped,
              "disk_note": "Empty disk counters are NOT proof of no I/O; raw MTD/flash may not expose block statistics.",
              "summary": summarize(samples)}
    (out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Evidence saved to {out}")
    return 2 if stopped else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"AUDIT NOT COMPLETED: {exc}", file=sys.stderr)
        raise SystemExit(2)
