"""Pure host helpers for a read-only Luckfox audit; never controls hardware."""
import configparser
import math
import re

# Candidates only. Encoder output FPS is NOT evidence of sensor or measured FPS.
# Leave sensor/ISP timing unchanged until the real camera supports a lower rate.
PREVIEW_DISABLED = {
    ("audio.0", "enable"): "0",
    ("audio.0", "enable_vqe"): "0",
    ("video.source", "enable_npu"): "0",
    ("video.source", "enable_ivs"): "0",
    ("video.source", "enable_jpeg"): "0",
    ("video.source", "enable_venc_0"): "1",
    ("video.source", "enable_venc_1"): "0",
    ("video.source", "enable_venc_2"): "0",
    ("video.source", "enable_rtsp"): "1",
    ("video.source", "enable_rtmp"): "0",
    ("storage.0", "enable"): "0",
    ("storage.1", "enable"): "0",
    ("storage.2", "enable"): "0",
}


def parse_ini(text):
    cfg = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    try:
        cfg.read_string(text)
    except configparser.Error as exc:
        raise ValueError(f"invalid INI: {exc}") from exc
    return cfg


def preview_candidate(text, fps):
    """Preserve all untargeted lines/comments. Does NOT write/upload/restart."""
    if type(fps) is not int or fps not in (3, 5):
        raise ValueError("preview FPS must be 3 or 5")
    changes = dict(PREVIEW_DISABLED)
    changes.update({("video.0", "dst_frame_rate_num"): str(fps),
                    ("video.0", "dst_frame_rate_den"): "1",
                    ("video.0", "gop"): str(2 * fps),
                    ("video.0", "video_type"): "videoStream"})
    return patch_ini(text, changes)


def patch_ini(text, changes):
    """Line-preserving validated option patch, no I/O."""
    cfg = parse_ini(text)
    for (section, key) in changes:
        if not cfg.has_option(section, key):
            raise ValueError(f"missing required config: {section}.{key}")
    section = None
    found = set()
    lines = []
    for line in text.splitlines(keepends=True):
        match = re.match(r"^\s*\[([^]]+)\]", line)
        if match:
            section = match.group(1)
        entry = re.match(r"^(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*?)(\r?\n)?$", line)
        target = (section, entry.group(2)) if entry else None
        if target in changes:
            if target in found:
                raise ValueError(f"duplicate config: {target}")
            found.add(target)
            comment = entry.group(4).partition(";")[2]
            suffix = " ;" + comment if comment else ""
            line = entry.group(1) + entry.group(2) + entry.group(3) + changes[target] + suffix + (entry.group(5) or "")
        lines.append(line)
    if found != changes.keys():
        raise ValueError("config patch incomplete")
    result = "".join(lines)
    checked = parse_ini(result)
    for (section, key), expected in changes.items():
        if checked.get(section, key) != expected:
            raise ValueError("config round-trip validation failed")
    return result


def camera_preview_candidate(text, fps=10):
    """Observed RV1103/SC3336 floor: request 10; must verify actual FPS on board.
    Preview only, no PPE inference. No sensor register or driver modifications.
    """
    if type(fps) is not int or fps != 10:
        raise ValueError("camera profile only supports verified request 10 FPS")
    changes = dict(PREVIEW_DISABLED)
    changes.update({("video.0", "src_frame_rate_num"): "10",
                    ("video.0", "src_frame_rate_den"): "1",
                    ("video.0", "dst_frame_rate_num"): "10",
                    ("video.0", "dst_frame_rate_den"): "1",
                    ("video.0", "gop"): "20",
                    ("video.0", "video_type"): "videoStream",
                    ("isp.0.adjustment", "fps"): "10"})
    return patch_ini(text, changes)


def idle_boot_candidate(text):
    """Wrap ONLY known vendor demo launch; drivers/network/boot remain untouched."""
    if 'apd-camera-idle' in text:
        raise ValueError("idle guard already present")
    launch = ('\tif [ -d "/oem/usr/share/iqfiles" ];then\n'
              '\t\trkipc -a /oem/usr/share/iqfiles &\n'
              '\telse\n\t\trkipc &\n\tfi')
    if text.count(launch) != 1:
        raise ValueError("unknown vendor launch script; manual review required")
    replacement = ('\t# APD development idle: preserve drivers/network; skip demo only.\n'
                   '\tif [ -f /userdata/apd-camera-idle ]; then\n'
                   '\t\techo "APD development idle: camera/demo monitoring OFF"\n'
                   '\telse\n' + ''.join('\t'+line+'\n' for line in launch.splitlines()) + '\tfi')
    return text.replace(launch, replacement)


def blocks(text):
    out = {}
    current = None
    for line in text.replace("\r", "").splitlines():
        if line.startswith("@@ "):
            current = line[3:].strip()
            out[current] = []
        elif current:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def cpu_counters(text):
    for line in text.splitlines():
        values = line.split()
        if values and values[0] == "cpu":
            ticks = [int(x) for x in values[1:9]]  # omit guest: already included
            if len(ticks) < 4 or any(x < 0 for x in ticks):
                raise ValueError("invalid CPU counters")
            return sum(ticks), ticks[3], ticks[4] if len(ticks) > 4 else 0
    raise ValueError("aggregate CPU counters missing")


def cpu_usage(previous, current):
    total, idle, wait = (b-a for a,b in zip(previous, current))
    if total <= 0 or idle < 0 or wait < 0 or idle + wait > total:
        raise ValueError("invalid counters: reboot or counter rollback")
    # iowait reported separately, not counted as active execution.
    return {"busy_percent": 100*(total-idle-wait)/total,
            "iowait_percent": 100*wait/total}


def temperature(raw):
    value = float(raw) / 1000
    if not math.isfinite(value) or not -40 <= value <= 150:
        raise ValueError("missing/invalid thermal reading")
    return value


def disk_sectors(text):
    """Whole-device counters only. Never sum device AND its partitions."""
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 14 and re.fullmatch(r"mmcblk[0-9]+|sd[a-z]+|nvme[0-9]+n[0-9]+", fields[2]):
            result[fields[2]] = (int(fields[5]), int(fields[9]))
    return result


def disk_delta(previous, current):
    out = {}
    for name in previous.keys() & current.keys():
        read, write = (b-a for a,b in zip(previous[name], current[name]))
        if read < 0 or write < 0:
            raise ValueError("disk counters went backwards")
        # Linux diskstats sectors always use 512 bytes, regardless of sector size.
        out[name] = {"read_bytes": read*512, "write_bytes": write*512}
    return out


def summarize(samples):
    temps = [s["temperature_c"] for s in samples if s.get("temperature_c") is not None]
    busy = [s["cpu"]["busy_percent"] for s in samples if s.get("cpu")]
    return {"samples": len(samples), "temperature_min_c": min(temps) if temps else None,
            "temperature_max_c": max(temps) if temps else None,
            "temperature_mean_c": sum(temps)/len(temps) if temps else None,
            "cpu_busy_mean_percent": sum(busy)/len(busy) if busy else None,
            "thermal_safety_verified": False,
            "measured_camera_fps": None, "measured_inference_fps": None}
