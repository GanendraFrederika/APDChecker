#!/bin/sh
# Supervised read-only probe; no camera, AI, GPIO, UART or service changes.
# Upload/run ONLY after operator has resolved/checked the overheating issue.
# Bounded 1Hz, at most 60 samples. Missing sensor stays null, never "safe".
set -eu
LC_ALL=C
export LC_ALL
samples="${1:-10}"
case "$samples" in ''|*[!0-9]*) echo 'samples must be integer 1..60' >&2; exit 2;; esac
if [ "$samples" -lt 1 ] || [ "$samples" -gt 60 ]; then
    echo 'samples must be integer 1..60' >&2
    exit 2
fi
seq=1
while [ "$seq" -le "$samples" ]; do
    read -r uptime ignored < /proc/uptime
    case "$uptime" in ''|*[!0-9.]*) echo 'invalid uptime' >&2; exit 3;; esac
    raw=null
    sensor=null
    if [ -r /sys/class/thermal/thermal_zone0/temp ]; then
        value=$(cat /sys/class/thermal/thermal_zone0/temp)
        case "$value" in ''|*[!0-9-]*) raw=null;; *) raw="$value";; esac
    fi
    if [ -r /sys/class/thermal/thermal_zone0/type ]; then
        value=$(cat /sys/class/thermal/thermal_zone0/type)
        case "$value" in ''|*[!a-zA-Z0-9_-]*) sensor=null;; *) sensor="\"$value\"";; esac
    fi
    printf '{"schema_version":1,"kind":"BOARD_HEARTBEAT","seq":%s,"uptime_seconds":%s,"thermal_zone0_raw":%s,"thermal_zone0_type":%s,"probe_only":true,"ai_running":false,"hardware_outputs_enabled":false}\n' "$seq" "$uptime" "$raw" "$sensor"
    seq=$((seq+1))
    if [ "$seq" -le "$samples" ]; then sleep 1; fi
done
