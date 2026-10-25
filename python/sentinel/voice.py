"""Friendly voice lines on the PC speaker (Indonesian, pre-generated MP3).

Playback runs in a persistent PowerShell process using the Windows WPF MediaPlayer,
so the AI loop never blocks and no extra Python audio packages are needed.
Lines: assets/voice/*.mp3 (made with edge-tts, voice id-ID-GadisNeural).
"""
from pathlib import Path
import random
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = ROOT / "assets/voice"

PLAYER = r'''
Add-Type -AssemblyName PresentationCore
$p = New-Object System.Windows.Media.MediaPlayer
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null -or $line -eq 'QUIT') { break }
  $parts = $line.Split('|')
  $p.Volume = [double]$parts[0]
  $p.Open([Uri]$parts[1])
  $p.Play()
}
'''


def greeting_key(hour=None):
    hour = time.localtime().tm_hour if hour is None else hour
    if 4 <= hour < 11:
        return "pagi"
    if 11 <= hour < 15:
        return "siang"
    if 15 <= hour < 18:
        return "sore"
    return "malam"


class Voice:
    def __init__(self, volume=0.5, cooldown=6.0):
        self.volume = volume
        self.cooldown = cooldown
        self.enabled = True
        self._last = 0.0
        self._lock = threading.Lock()
        self._proc = None
        self.last_line = ""

    def _ensure(self):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PLAYER],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def say(self, key, force=False):
        """Play one line; returns True when it was played (respects the cooldown)."""
        path = VOICE_DIR / f"{key}.mp3"
        now = time.monotonic()
        with self._lock:
            if not self.enabled or not path.exists():
                return False
            if not force and now - self._last < self.cooldown:
                return False
            self._last = now
            try:
                self._ensure()
                self._proc.stdin.write(f"{self.volume:.2f}|{path.as_uri()}\n")
                self._proc.stdin.flush()
            except OSError:
                self._proc = None
                return False
            self.last_line = key
            return True

    def greet(self):
        """Random friendly greeting: Halo / Hai / time of day / Hati-hati ya."""
        return self.say(random.choice(["halo", "hi", greeting_key(), greeting_key(), "hati_hati"]))

    def close(self):
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.stdin.write("QUIT\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=2)
                except Exception:
                    self._proc.kill()
            self._proc = None
