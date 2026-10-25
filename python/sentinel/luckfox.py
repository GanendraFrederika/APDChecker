"""Luckfox Pico Mini B camera helpers over ADB (development host only).

The vendor adbd supports PTY shell only, so commands go through `adb shell`
and results are parsed from text (the remote exit code is not reliable).
Camera power/thermal safety stays with the on-board guard
(/userdata/apd-preview-session.sh): bounded duration, thermal cutoff, no restart.
"""
import hashlib
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
ADB = ROOT / "platform-tools/adb.exe"
# Proven light profile (11-10-2026 thermal recovery): 2304x1296 H.265 @ 10 fps,
# NPU / JPEG / IVS / substream / audio OFF. The boot script restores the heavy
# factory profile whenever the sensor is missed at boot, so we re-apply it.
PROFILE = ROOT / "edge/luckfox/rkipc-sentinel-10fps.ini"
BACKUPS = ROOT / "docs/luckfox/debug/rkipc-backups"
RTSP_PORT = 18554
RTSP_URL = f"rtsp://127.0.0.1:{RTSP_PORT}/live/0"


class Luckfox:
    def __init__(self, serial=None, adb=ADB):
        self.serial = serial
        self.adb = Path(adb)

    def _cmd(self, *args, timeout=20):
        base = [str(self.adb)] + (["-s", self.serial] if self.serial else [])
        r = subprocess.run(base + list(args), capture_output=True, timeout=timeout)
        out = r.stdout.decode("utf-8", "replace").replace("\r", "")
        err = r.stderr.decode("utf-8", "replace").replace("\r", "")
        return r.returncode, out, err

    def shell(self, script, timeout=20):
        code, out, err = self._cmd("shell", "sh -c " + shlex.quote(script), timeout=timeout)
        if code:
            raise RuntimeError((err or out).strip() or "adb shell gagal")
        return out

    def present(self):
        try:
            code, out, _ = self._cmd("get-state", timeout=8)
        except subprocess.TimeoutExpired:
            return False
        return code == 0 and out.strip() == "device"

    def ensure_forward(self):
        """True if the RTSP forward had to be (re)created (lost after a replug)."""
        _, out, _ = self._cmd("forward", "--list", timeout=8)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1:] == [f"tcp:{RTSP_PORT}", "tcp:554"] and \
                    (self.serial is None or parts[0] == self.serial):
                return False
        code, _, err = self._cmd("forward", f"tcp:{RTSP_PORT}", "tcp:554", timeout=10)
        if code:
            raise RuntimeError("adb forward gagal: " + err.strip())
        return True

    def camera_running(self):
        return self.shell("pidof rkipc >/dev/null && echo RUN || echo IDLE").strip().endswith("RUN")

    def profile_status(self):
        want = hashlib.sha256(PROFILE.read_bytes()).hexdigest()
        out = self.shell("sha256sum /userdata/rkipc.ini 2>/dev/null || echo MISSING").split()
        have = out[0] if out and out[0] != "MISSING" else None
        return want, have

    def ensure_profile(self):
        """OK / APPLIED / BUSY. Backs up whatever was there before replacing it."""
        want, have = self.profile_status()
        if have == want:
            return "OK"
        if self.camera_running():
            return "BUSY"                      # never swap config under a running camera
        BACKUPS.mkdir(parents=True, exist_ok=True)
        if have:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self._cmd("pull", "/userdata/rkipc.ini", str(BACKUPS / f"rkipc-{stamp}-{have[:12]}.ini"),
                      timeout=30)
        code, _, err = self._cmd("push", str(PROFILE), "/tmp/apd-sentinel.ini", timeout=30)
        if code:
            raise RuntimeError("push profil gagal: " + err.strip())
        if self.shell("sha256sum /tmp/apd-sentinel.ini").split()[0] != want:
            raise RuntimeError("profil rusak saat transfer")
        self.shell("cp /tmp/apd-sentinel.ini /userdata/rkipc.ini && sync && rm -f /tmp/apd-sentinel.ini")
        if self.profile_status()[1] != want:
            raise RuntimeError("profil tidak tersimpan di /userdata")
        return "APPLIED"

    def start_camera(self, seconds=300, cutoff_c=70):
        return self.shell("pidof rkipc >/dev/null && echo ALREADY_RUNNING || "
                          f"sh /userdata/apd-previewctl.sh start {int(seconds)} {int(cutoff_c)}",
                          timeout=25).strip()

    def stop_camera(self):
        return self.shell("sh /userdata/apd-previewctl.sh stop", timeout=30).strip()

    def soc_dc(self):
        out = self.shell("cat /sys/class/thermal/thermal_zone0/temp").strip()
        return int(out) // 100 if out.isdigit() else None

    def prepare(self, seconds=300, cutoff_c=70):
        """Forward + light profile + guarded camera start. Returns a log list."""
        log = []
        if self.ensure_forward():
            log.append("RTSP forward dibuat")
        state = self.ensure_profile()
        if state == "BUSY":
            log.append("kamera jalan dengan profil lain: hentikan dulu")
            log.append(self.stop_camera())
            state = self.ensure_profile()
        log.append("profil kamera: " + state)
        log.append(self.start_camera(seconds, cutoff_c))
        return log
