#!/bin/sh
# Development preview only, no PPE, UART/GPIO, boot edit, or automatic restart.
STATE=/tmp/apd-vendor-npu-state
LOG=/tmp/apd-vendor-npu.log
SELF=/tmp/apd-vendor-npu-session.sh
case "$(tr -d '\000' </proc/device-tree/model)" in
 'Luckfox Pico Mini B') ;;
 *) echo 'ERROR wrong board'; exit 10;;
esac
valid_pid() { case "$1" in ''|*[!0-9]*) return 1;; esac; [ "${#1}" -le 9 ] && [ "$1" -gt 1 ]; }
guard_owned() {
 owner=$(cat "$STATE/owner" 2>/dev/null) || return 1
 valid_pid "$owner" && kill -0 "$owner" 2>/dev/null || return 1
 # Validate all argv, not grep on an arbitrary command substring.
 args=$(tr '\000' '\n' </proc/"$owner"/cmdline 2>/dev/null) || return 1
 first=$(printf '%s\n' "$args" | sed -n '1p')
 second=$(printf '%s\n' "$args" | sed -n '2p')
 third=$(printf '%s\n' "$args" | sed -n '3p')
 case "$first" in sh|/bin/sh) ;; *) return 1;; esac
 [ "$second" = "$SELF" ] && [ "$third" = run ]
}
case "$1" in
 start)
  seconds=${2:-60}
  case "$seconds" in ''|*[!0-9]*) echo INVALID_DURATION; exit 2;; esac
  [ "${#seconds}" -le 3 ] && [ "$seconds" -ge 10 ] && [ "$seconds" -le 300 ] || exit 2
  cutoff_c=${3:-60}
  case "$cutoff_c" in ''|*[!0-9]*) echo INVALID_CUTOFF; exit 2;; esac
  [ "${#cutoff_c}" -le 2 ] && [ "$cutoff_c" -ge 40 ] && [ "$cutoff_c" -le 78 ] || exit 2
  [ -f "$SELF" ] || { echo MISSING_GUARD; exit 20; }
  [ ! -d "$STATE" ] || { echo SESSION_LOCKED; exit 19; }
  pidof rkipc >/dev/null && { echo UNMANAGED_CAMERA_RUNNING; exit 18; }
  # All shell/session/camera descriptors redirected; do not hold ADB PTY open.
  nohup sh "$SELF" run "$seconds" "$cutoff_c" </dev/null >/tmp/apd-vendor-npu-guard.log 2>&1 &
  sleep 3
  guard_owned && pidof rkipc >/dev/null || { echo START_FAILED; tail -10 /tmp/apd-vendor-npu-guard.log; exit 13; }
  grep -q 'rtsp_demo.*bind socket to address failed' "$LOG" && { echo START_FAILED_RTSP_BIND; exit 17; }
  echo "VENDOR_NPU_PROCESS_STARTED_NOT_PPE GUARDED seconds=$seconds cutoff_C=$cutoff_c poll_seconds=2"
  ;;
 stop)
  if guard_owned; then
   kill -TERM "$owner" || exit 15
   n=0
   while [ -d "$STATE" ]; do
    n=$((n+1)); [ "$n" -lt 16 ] || { echo STOP_TIMEOUT; exit 16; }
    sleep 1
   done
  elif pidof rkipc >/dev/null || [ -d "$STATE" ]; then
   echo UNMANAGED_OR_STALE_SESSION_NO_SIGNAL_SENT; exit 18
  fi
  pidof rkipc >/dev/null && { echo CAMERA_STILL_RUNNING; exit 16; }
  echo PREVIEW_STOPPED
  ;;
 status)
  echo 'MONITORING/PPE INFERENCE: NOT DEPLOYED'
  if pidof rkipc; then
   echo PREVIEW_PROCESS_RUNNING
   guard_owned && echo LOCAL_GUARD_ACTIVE || echo UNMANAGED_CAMERA_RUNNING
  else echo CAMERA_IDLE; fi
  [ -f /userdata/apd-camera-idle ] && echo BOOT_MODE_IDLE || echo BOOT_MODE_VENDOR_DEMO
  cat /sys/class/thermal/thermal_zone0/temp
  grep '^APD_GUARD_' "$LOG" 2>/dev/null || true
  ;;
 *) echo 'Usage: sh apd-previewctl.sh start [10..300 seconds]|stop|status'; exit 2;;
esac
