#!/bin/sh
# Bounded development camera preview, NOT PPE inference or hardware power-off.
# Practical conservative cutoffs, not manufacturer temperature specifications.
# Runs locally, so USB loss does not depend on a successful PC stop command.
STATE=/tmp/apd-preview-session
LOG=/tmp/apd-preview.log
RUNTIME=/oem/usr/bin/rkipc
SELF=/userdata/apd-preview-session.sh
INTERVAL=2
STOP_RAW=60000
START_RAW=55000
MAX_SECONDS=300
MAX_LOG_BYTES=1048576

board_ok() {
 [ "$(tr -d '\000' </proc/device-tree/model)" = 'Luckfox Pico Mini B' ]
}
valid_uint() {
 case "$1" in ''|*[!0-9]*) return 1;; esac
 [ "${#1}" -le 9 ]
}
read_temp() {
 raw=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null) || return 1
 # This development guard refuses subzero/implausible readings too.
 valid_uint "$raw" && [ "$raw" -le 150000 ]
}
read_time() {
 read up rest </proc/uptime || return 1
 now=${up%%.*}
 valid_uint "$now"
}
usb_ok() {
 found=0
 for f in /sys/class/udc/*/state; do
  [ -f "$f" ] || continue
  found=1
  [ "$(cat "$f" 2>/dev/null)" = configured ] || return 1
 done
 [ "$found" = 1 ]
}
# rkipc comm contains no spaces; reject any other process before interpreting stat.
process_token() {
 valid_uint "$1" || return 1
 [ "$(cat /proc/"$1"/comm 2>/dev/null)" = rkipc ] || return 1
 awk '{print $22}' /proc/"$1"/stat 2>/dev/null
}
owned_alive() {
 token=$(process_token "$camera_pid") || return 1
 [ -n "$camera_token" ] && [ "$token" = "$camera_token" ]
}
release_lock() {
 # Fixed paths only; never recursive cleanup, and only the session owner cleans.
 [ "$(cat "$STATE/owner" 2>/dev/null)" = "$$" ] || return
 rm -f "$STATE/owner" "$STATE/camera_pid" "$STATE/camera_token"
 rmdir "$STATE" 2>/dev/null || true
}
finish() {
 trap '' TERM INT HUP
 if owned_alive; then
  kill -TERM "$camera_pid" 2>/dev/null || true
  n=0
  while owned_alive && [ "$n" -lt 10 ]; do sleep 1; n=$((n+1)); done
  if owned_alive; then
   echo 'APD_GUARD_ESCALATE_KILL' >>"$LOG"
   kill -KILL "$camera_pid" 2>/dev/null || true
  fi
 fi
 [ -n "$camera_pid" ] && wait "$camera_pid" 2>/dev/null
 echo "APD_GUARD_STOP=$reason" >>"$LOG"
 release_lock
}
run() {
 valid_uint "$1" && [ "$1" -ge 10 ] && [ "$1" -le "$MAX_SECONDS" ] || exit 2
 board_ok || exit 10
 read_temp && [ "$raw" -lt "$START_RAW" ] || exit 12
 read_time && usb_ok || exit 11
 # No takeover: concurrent, stale, or externally owned camera is an error.
 pidof rkipc >/dev/null && exit 18
 mkdir "$STATE" 2>/dev/null || { echo SESSION_LOCKED; exit 19; }
 echo "$$" >"$STATE/owner" || { rmdir "$STATE"; exit 19; }
 camera_pid=''; camera_token=''; reason=SUPERVISOR_EXIT
 trap 'reason=STOP_REQUEST; exit 0' TERM INT HUP
 trap finish EXIT
 start=$now; deadline=$((start+$1))
 : >"$LOG"
 echo "APD_GUARD_START seconds=$1 cutoff_raw=$STOP_RAW" >>"$LOG"
 "$RUNTIME" -a /oem/usr/share/iqfiles -c /userdata/rkipc.ini -l 0 </dev/null >>"$LOG" 2>&1 &
 camera_pid=$!
 # Store process identity immediately; never signal an unrelated reused PID.
 camera_token=$(process_token "$camera_pid")
 n=0
 while [ -z "$camera_token" ] && kill -0 "$camera_pid" 2>/dev/null && [ "$n" -lt 3 ]; do
  sleep 1; n=$((n+1)); camera_token=$(process_token "$camera_pid")
 done
 [ -n "$camera_token" ] || { reason=CAMERA_START_FAILED; exit 13; }
 echo "$camera_pid" >"$STATE/camera_pid"
 echo "$camera_token" >"$STATE/camera_token"
 previous=$now
 while owned_alive; do
  read_temp || { reason=INVALID_THERMAL_SENSOR; exit 11; }
  [ "$raw" -lt "$STOP_RAW" ] || { reason=THERMAL_CUTOFF; exit 12; }
  read_time && [ "$now" -ge "$previous" ] || { reason=INVALID_MONOTONIC_CLOCK; exit 11; }
  [ "$now" -lt "$deadline" ] || { reason=TIME_LIMIT; exit 0; }
  previous=$now
  usb_ok || { reason=USB_NOT_CONFIGURED; exit 11; }
  if grep -q 'rtsp_demo.*bind socket to address failed' "$LOG"; then
   reason=RTSP_BIND_FAILED; exit 17
  fi
  bytes=$(wc -c <"$LOG") || { reason=LOG_READ_FAILED; exit 11; }
  valid_uint "$bytes" && [ "$bytes" -lt "$MAX_LOG_BYTES" ] || { reason=LOG_LIMIT; exit 11; }
  sleep "$INTERVAL"
 done
 reason=CAMERA_EXIT
}
case "$1" in
 run) run "$2";;
 *) echo 'Internal usage: apd-preview-session.sh run 10..300'; exit 2;;
esac
