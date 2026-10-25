#!/bin/sh
# Development preview only. No PPE inference, GPIO or UART.
case "$(tr -d '\000' </proc/device-tree/model)" in
 'Luckfox Pico Mini B') ;;
 *) echo 'ERROR wrong board'; exit 10 ;;
esac
case "$1" in
 start)
  if pidof rkipc >/dev/null; then echo ALREADY_RUNNING; exit 0; fi
  temp=$(cat /sys/class/thermal/thermal_zone0/temp) || exit 11
  [ "$temp" -lt 65000 ] || { echo TOO_HOT_TO_START; exit 12; }
  nohup /oem/usr/bin/rkipc -a /oem/usr/share/iqfiles -c /userdata/rkipc.ini -l 0 </dev/null >/tmp/apd-preview.log 2>&1 &
  sleep 3
  pidof rkipc >/dev/null || { echo START_FAILED; tail -30 /tmp/apd-preview.log; exit 13; }
  if grep -q 'rtsp_demo.*bind socket to address failed' /tmp/apd-preview.log; then
   echo 'START_FAILED_RTSP_BIND: stop preview; reboot to clear inherited sockets'
   exit 17
  fi
  echo PREVIEW_STARTED
  ;;
 stop)
  for pid in $(pidof rkipc); do
   [ "$(cat /proc/$pid/comm)" = rkipc ] || exit 14
   kill -TERM "$pid" || exit 15
  done
  n=0
  while pidof rkipc >/dev/null; do
   n=$((n+1)); [ "$n" -lt 12 ] || { echo STOP_TIMEOUT; exit 16; }
   sleep 1
  done
  echo PREVIEW_STOPPED
  ;;
 status)
  echo 'MONITORING/PPE INFERENCE: NOT DEPLOYED'
  if pidof rkipc; then
   echo PREVIEW_PROCESS_RUNNING
   if grep -q 'rtsp_demo.*bind socket to address failed' /tmp/apd-preview.log 2>/dev/null; then
    echo PREVIEW_RTSP_BIND_FAILED
   fi
  else
   echo CAMERA_IDLE
  fi
  if [ -f /userdata/apd-camera-idle ]; then echo BOOT_MODE_IDLE; else echo BOOT_MODE_VENDOR_DEMO; fi
  cat /sys/class/thermal/thermal_zone0/temp
  ;;
 *) echo 'Usage: sh /userdata/apd-previewctl.sh start|stop|status'; exit 2 ;;
esac
