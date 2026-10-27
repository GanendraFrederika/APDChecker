"""Hardware-in-the-loop test of the APD Sentinel rig WITHOUT a camera.

The real Arduino, servos, LCD, speaker and fans are driven by the real brain code
(tracker + brain + link). Only the camera is replaced by "virtual people" that stand
at fixed WORLD angles: a person is seen only while the real servo pose (from MCU
telemetry) points the field of view at them, exactly like the real camera. So patrol,
interrupt-on-detection, lock, follow, group, violation alarm, gesture animation, LCD
text and smart-fan control are all exercised on the hardware.

Run:  .venv\\Scripts\\python.exe scripts\\sentinel_hil.py --port COM6 [--volume 30] [--mute]
The rig MOVES (full pan range) and the siren sounds ~3 s (unless --mute).
      .venv\\Scripts\\python.exe scripts\\sentinel_hil.py --sim
Same scenario against the firmware core compiled for the PC (tests/native/sim_mcu.c):
no hardware, so logic faults can be told apart from wiring/power faults.
"""
import argparse
import ctypes
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


class SimSerial:
    """pyserial look-alike around the firmware core DLL (opening = MCU reset)."""
    lib = None

    @classmethod
    def build(cls):
        if cls.lib is not None:
            return cls.lib
        out = ROOT / ".cache" / "sim_mcu.dll"
        out.parent.mkdir(exist_ok=True)
        zig = ROOT / ".tools/ziglang-0.13.0/ziglang/zig.exe"
        subprocess.run([str(zig), "cc", "-shared", "-O1", "-std=c99", "-o", str(out),
                        str(ROOT / "tests/native/sim_mcu.c"),
                        str(ROOT / "arduino/apd_sentinel/sentinel_core.c")], check=True)
        lib = ctypes.CDLL(str(out))
        lib.sim_boot.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_int)
        lib.sim_io.argtypes = (ctypes.c_uint32, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int)
        lib.sim_io.restype = ctypes.c_int
        cls.lib = lib
        return lib

    def __init__(self, port, baud, timeout=0.02, write_timeout=0.5):
        self.lib = self.build()
        self.timeout = timeout
        self.t0 = time.monotonic()
        self.pending = bytearray()
        self.out = ctypes.create_string_buffer(8192)
        self.lib.sim_boot(self._ms(), -32768, -32768)     # no DS18B20 (like the rig today)

    def _ms(self):
        return int((time.monotonic() - self.t0) * 1000) + 1000

    def write(self, data):
        self.pending.extend(data)
        return len(data)

    def read(self, n):
        time.sleep(self.timeout)
        data, self.pending = bytes(self.pending), bytearray()
        k = self.lib.sim_io(self._ms(), data, len(data), self.out, min(n, 8192))
        return self.out.raw[:k]

    def close(self):
        pass

from sentinel.brain import Brain, BrainConfig      # noqa: E402
from sentinel.link import SentinelLink             # noqa: E402
from sentinel.tracker import Tracker               # noqa: E402
from sentinel.types import Command                 # noqa: E402

HFOV_DD, VFOV_DD = 520, 880          # upright camera view (portrait sensor), deci-degrees


@dataclass
class Person:
    pan: float                       # world angle of the body centre (servo dd)
    tilt: float
    items: dict = field(default_factory=lambda: dict(helmet="PRESENT", vest="PRESENT", shoes="PRESENT"))
    width: float = 110.0
    height: float = 380.0

    def detection(self):
        box = (self.pan - self.width / 2, self.tilt + self.height / 2,
               self.pan + self.width / 2, self.tilt - self.height / 2)
        return dict(angle_box=box, pixel_box=(0, 0, 1, 1), regions={},
                    evidence={k: (v, 0.9, "SIM") for k, v in self.items.items()})


class Rig:
    def __init__(self, port, volume, sound, sim=False):
        self.link = SentinelLink(port, serial_factory=SimSerial if sim else None)
        self.link.set_volume(volume)
        self.sound = sound
        self.brain = Brain(self.link.limits, BrainConfig(patrol_interval=3600))
        self.brain.idle_since = time.monotonic()        # patrols only when the test asks
        self.tracker = Tracker()
        self.people = {}
        self.fx, self.fx_id = "-", 0
        self.manual = None
        self.t0 = time.monotonic()
        self.lcd_log, self.mode_log = [], []
        self.checks = []
        self.max_pan, self.min_pan = -1, 9999
        self.sounding_seen = False
        self.vcc_min = 99999
        self.events_printed = 0
        self.worst_jump, self._prev_tele, self._prev_v = 0.0, None, None

    # ------------------------------------------------------------ plumbing
    def now(self):
        return time.monotonic() - self.t0

    def pose(self):
        t = self.link.telemetry
        return (t.pan, t.tilt) if t else (900, 1800)

    def visible(self, p):
        pan, tilt = self.pose()
        return abs(p.pan - pan) < 0.45 * HFOV_DD and abs(p.tilt - tilt) < 0.45 * VFOV_DD

    def step(self):
        now = time.monotonic()
        self.brain.set_limits(self.link.limits)
        dets = [p.detection() for p in self.people.values() if self.visible(p)]
        self.tracker.update(dets, now)
        tracks = self.tracker.visible(now, max_age=0.4)
        if self.manual:
            cmd = Command("T", self.manual[0], self.manual[1], 60)
        else:
            cmd, _ = self.brain.step(now, tracks, pose=self.pose())
        locked = self.tracker.get(cmd.trk) if cmd.trk else None
        items = locked.item_code() if locked is not None else cmd.items
        cmd = Command(cmd.mode, cmd.pan, cmd.tilt, cmd.spd, (items + "---")[:3], cmd.alarm and self.sound,
                      cmd.ppl, cmd.viol, cmd.trk, self.fx, self.fx_id, self.sound)
        self.link.set_command(cmd)
        if not self.mode_log or self.mode_log[-1][1] != cmd.mode:
            self.mode_log.append((round(self.now(), 1), cmd.mode))
            print(f"{self.now():6.1f}s  mode {cmd.mode}  pan/tilt cmd {cmd.pan}/{cmd.tilt}", flush=True)
        lcd = self.link.lcd
        if lcd and (not self.lcd_log or self.lcd_log[-1][1] != lcd):
            self.lcd_log.append((round(self.now(), 1), lcd))
            print(f"{self.now():6.1f}s  LCD [{lcd[0]}] [{lcd[1]}]", flush=True)
        tele = self.link.telemetry
        if tele:
            self.max_pan, self.min_pan = max(self.max_pan, tele.pan), min(self.min_pan, tele.pan)
            self.sounding_seen |= tele.sounding
            self.vcc_min = min(self.vcc_min, tele.vcc_mv or 99999)
            prev = self._prev_tele
            if prev is not None and tele.ms != prev.ms and 0 < tele.ms - prev.ms <= 120:
                dt = (tele.ms - prev.ms) / 1000.0
                v = ((tele.pan - prev.pan) / dt, (tele.tilt - prev.tilt) / dt)
                if self._prev_v is not None:
                    jump = max(abs(v[0] - self._prev_v[0]), abs(v[1] - self._prev_v[1])) * 0.05 / dt
                    self.worst_jump = max(self.worst_jump, jump)
                self._prev_v = v
            elif prev is None or tele.ms != prev.ms:
                self._prev_v = None
            self._prev_tele = tele
        events = self.link.events
        for stamp, text in events[len(events) - min(len(events), self.link_event_count_new()):]:
            print(f"{self.now():6.1f}s  [link] {text}", flush=True)
        return cmd

    def link_event_count_new(self):
        """Number of link events not printed yet (the list is bounded to 50)."""
        total = self.link.event_total
        new = total - self.events_printed
        self.events_printed = total
        return max(0, min(new, len(self.link.events)))

    def run(self, seconds, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            cmd = self.step()
            if until is not None and until(cmd):
                return True
            time.sleep(0.1)
        return False

    def check(self, name, ok, detail=""):
        self.checks.append((name, bool(ok), detail))
        print(f"   [{'OK ' if ok else 'GAGAL'}] {name} {detail}", flush=True)

    def section_end(self):
        resets = sum(1 for _, text in self.link.events if text.startswith("READY,SENTINEL") and ",00000000," in text)
        print(f"   (Vcc minimum {self.vcc_min} mV, link {'OK' if self.link.connected else 'PUTUS'}, "
              f"READY boot terlihat {resets}x)", flush=True)
        self.vcc_min = 99999


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM6")
    ap.add_argument("--volume", type=int, default=50)
    ap.add_argument("--mute", action="store_true")
    ap.add_argument("--sim", action="store_true", help="firmware core on the PC instead of the Arduino")
    args = ap.parse_args()
    if args.sim:
        SimSerial.build()                        # compile before the link's connect timeout runs
    rig = Rig("SIM" if args.sim else args.port, args.volume, not args.mute, sim=args.sim)
    link = rig.link.start()
    deadline = time.monotonic() + 15
    while not link.connected and time.monotonic() < deadline:
        time.sleep(0.1)
    if not link.connected:
        print("Arduino tidak terhubung:", link.status)
        return 2
    print("Terhubung:", link.version, link.limits, flush=True)
    rig.run(4)                                       # boot glide home, LCD shows "Memantau"

    print("\n== 1. Zona: minta kanan-atas (pan 0, tilt 180) -> firmware harus membatasi ke 170")
    rig.manual = (0, 1800)
    rig.run(16, until=lambda c: link.telemetry and abs(link.telemetry.pan) <= 2 and not link.telemetry.moving)
    t = link.telemetry
    rig.check("atap tilt 170 derajat saat mentok kanan", t and t.pan <= 2 and t.tilt == 1700 and t.clamped,
              f"(pan {t.pan}, tilt {t.tilt}, clamped {t.clamped})")
    rig.manual = (900, 1800)
    rig.run(14, until=lambda c: link.telemetry and abs(link.telemetry.pan - 900) <= 2 and not link.telemetry.moving)
    rig.manual = None
    rig.section_end()

    print("\n== 2. Patroli: kiri, kanan, kiri, kanan, kiri, tengah (dipercepat untuk tes)")
    rig.brain.cfg.patrol_speed = 60
    rig.brain.mode, rig.brain.idle_since, rig.brain.last_people_at = "I", -1e9, -1e9
    rig.max_pan, rig.min_pan = -1, 9999
    seen = {"P": False}

    def patrol_done(c):
        seen["P"] |= c.mode == "P"
        return seen["P"] and c.mode == "I" and not link.telemetry.moving
    rig.run(60, until=patrol_done)
    rig.check("patroli sampai kiri (pan >= 130 derajat)", rig.max_pan >= 1300, f"(maks {rig.max_pan / 10:.1f})")
    rig.check("patroli sampai kanan (pan <= 15 derajat)", rig.min_pan <= 150, f"(min {rig.min_pan / 10:.1f})")
    rig.check("patroli kembali ke tengah", abs(rig.pose()[0] - 900) <= 10, f"(pan {rig.pose()[0] / 10:.1f})")
    rig.section_end()

    print("\n== 3. Patroli lagi, orang berdiri di pan 40 derajat -> patroli dihentikan, kamera mengunci")
    rig.brain.mode, rig.brain.idle_since, rig.brain.last_people_at = "I", -1e9, -1e9
    rig.run(1.0)
    rig.people["A"] = Person(400, 1650)
    locked = rig.run(30, until=lambda c: c.mode == "T")
    rig.check("patroli diinterupsi dan orang dikunci (mode T)", locked)
    rig.run(5)
    err = abs(rig.pose()[0] - 400)
    rig.check("kamera menghadap orang (selisih <= 8 derajat)", err <= 80, f"(selisih {err / 10:.1f} derajat)")
    rig.section_end()

    print("\n== 4. Orang berjalan ke kiri 10 derajat/detik -> kamera mengikuti")
    worst = 0
    for _ in range(60):
        rig.people["A"].pan += 10
        rig.step()
        if rig.now() > 0:
            worst = max(worst, abs(rig.pose()[0] - rig.people["A"].pan))
        time.sleep(0.1)
    rig.run(4)
    err = abs(rig.pose()[0] - rig.people["A"].pan)
    rig.check("tetap terkunci saat berjalan", rig.brain.mode in ("T", "A"), f"(mode {rig.brain.mode})")
    rig.check("kamera menyusul orang (selisih akhir <= 8 derajat)", err <= 80,
              f"(selisih maks saat jalan {worst / 10:.1f}, akhir {err / 10:.1f})")
    rig.section_end()

    print("\n== 5. Orang kedua masuk -> mode grup, keduanya dibingkai")
    a = rig.people["A"]
    rig.people["B"] = Person(a.pan + 140, 1680)
    grouped = rig.run(12, until=lambda c: c.mode == "G")
    rig.check("mode grup (G) dengan 2 orang", grouped)
    rig.run(4)
    rig.section_end()

    print("\n== 6. Orang A melepas helm -> pelanggaran, tetap dikunci walau B ada, sirine")
    rig.people["A"].items["helmet"] = "ABSENT"
    viol = rig.run(10, until=lambda c: c.mode == "V" and c.alarm)
    rig.check("pelanggar dikunci + alarm", viol)
    rig.run(3.5)
    rig.check("sirine/relay benar-benar bunyi (telemetri)", rig.sounding_seen or args.mute,
              "(dibisukan --mute)" if args.mute else "")
    rig.check("lock tetap ke pelanggar walau ada 2 orang", rig.brain.lock_id and
              rig.tracker.get(rig.brain.lock_id) is not None and
              rig.tracker.get(rig.brain.lock_id).items["helmet"].state == "ABSENT")
    del rig.people["B"]
    rig.people["A"].items["helmet"] = "PRESENT"
    back = rig.run(12, until=lambda c: c.mode == "T")
    rig.check("helm dipakai lagi -> alarm berhenti, kembali cek", back)
    rig.section_end()

    print("\n== 7. Jempol -> animasi angguk + nada")
    rig.fx, rig.fx_id = "N", 1
    rig.run(3)
    rig.fx = "-"
    rig.check("LCD menampilkan 'Jempol diterima'", any("Jempol" in r[1][0] for r in rig.lcd_log))
    rig.run(2)
    rig.section_end()

    print("\n== 8. Orang pergi -> celingak-celinguk mencari, lalu home")
    del rig.people["A"]
    searched = rig.run(6, until=lambda c: c.mode == "S")
    rig.check("mode mencari (S)", searched)
    home = rig.run(15, until=lambda c: c.mode == "I")
    rig.check("kembali diam di home", home)
    rig.section_end()

    print("\n== 9. Kipas pintar: suhu SoC Pico (ENV) dan perintah manual")
    link.set_env(700)                                   # 70.0 C SoC
    rig.run(4)
    rig.check("SoC 70 C -> kipas Pico 100%", link.telemetry.fan_p == 255, f"(duty {link.telemetry.fan_p})")
    link.set_env(300)                                   # 30.0 C
    rig.run(4)
    rig.check("SoC 30 C -> kipas Pico mati", link.telemetry.fan_p == 0, f"(duty {link.telemetry.fan_p})")
    link.send_raw("FAN", "A", 255)
    rig.run(2.5)
    rig.check("kipas Arduino manual 100%", link.telemetry.fan_a == 255, f"(duty {link.telemetry.fan_a})")
    link.send_raw("FAN", "A", -1)
    rig.run(2.5)
    tA = link.telemetry.temp_a
    rig.check("kipas Arduino kembali otomatis", (link.telemetry.fan_a == 0) if tA is None else
              (link.telemetry.fan_a != 255 or tA >= 55),
              f"(duty {link.telemetry.fan_a}, DS18B20 {'%.1f C' % tA if tA is not None else 'belum dipasang -> kipas mati'})")
    rig.section_end()

    print("\n== 10. LCD tidak spam: teks normal berganti maksimal tiap 3 detik")
    # Urgent and event screens may replace text at once; a NORMAL screen may only
    # replace a non-urgent screen after it has been shown for 3 s.
    urgent = ("LINK AI PUTUS", "!! ALARM", "MODE KALIBRASI", "GANGGUAN", "APD SENTINEL 3")
    event = ("Jempol diterima", "Lengkapi APD", "Halo juga", "Hmm... mencari")
    kind = lambda row: "U" if row.startswith(urgent) else "E" if row.startswith(event) else "N"
    spam = [(b[0], b[1][0]) for a, b in zip(rig.lcd_log, rig.lcd_log[1:])
            if kind(b[1][0]) == "N" and kind(a[1][0]) != "U" and b[0] - a[0] < 2.8]
    rig.check("teks normal tidak berganti < 3 detik", not spam,
              f"({len(rig.lcd_log)} pergantian dalam {rig.now():.0f} s, terlalu cepat: {spam[:3]})")
    rig.check("tidak ada 'LINK AI PUTUS' palsu", not any(r[1][0].startswith("LINK AI PUTUS") for r in rig.lcd_log))
    rig.check("Arduino tidak reboot selama tes", link.resets == 0,
              f"(reboot {link.resets}x, gangguan USB sesaat {link.io_glitches}x)")
    rig.check("gerak servo halus (lompatan kecepatan output)", rig.worst_jump < 400,
              f"(terburuk {rig.worst_jump:.0f} dd/s per 50 ms dari telemetri)")
    rig.section_end()
    link.set_command(Command("I", 900, 1800, 30))
    time.sleep(0.5)
    link.stop()
    ok = sum(1 for c in rig.checks if c[1])
    print(f"\nHASIL: {ok}/{len(rig.checks)} lulus")
    for name, good, detail in rig.checks:
        print(f"  {'OK   ' if good else 'GAGAL'} {name} {detail}")
    return 0 if ok == len(rig.checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
