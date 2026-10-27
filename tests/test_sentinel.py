"""APD Sentinel v3.1 brain-side tests (no camera, serial or Arduino needed)."""
import json
from pathlib import Path
import subprocess
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from sentinel import protocol as P                      # noqa: E402
from sentinel.brain import Brain                         # noqa: E402
from sentinel.geometry import CameraModel                # noqa: E402
from sentinel.interact import Interaction, NOD_COOLDOWN  # noqa: E402
from sentinel.gesture import Hand                        # noqa: E402
from sentinel.tracker import Tracker                     # noqa: E402
from sentinel.types import Command                       # noqa: E402


def det(box):
    return dict(angle_box=box, pixel_box=(100, 100, 300, 600), evidence={}, regions={})


class ProtocolTests(unittest.TestCase):
    def test_golden_vectors_match_firmware(self):
        self.assertEqual(P.hello("1A2B3C4D"), b"$HELLO,1A2B3C4D*C8\n")
        self.assertEqual(P.simple("PING", 7), b"$PING,7*43\n")
        self.assertEqual(P.simple("SAVE"), b"$SAVE*85\n")
        self.assertEqual(P.simple("VOL", 50), b"$VOL,50*04\n")

    def test_s_frame_v11_fields(self):
        frame = P.state("1A2B3C4D", 1, Command("T", 900, 1500, 60, "PPA", False, 1, 0, 3, "N", 7, True))
        self.assertEqual(frame, P.frame("S,1A2B3C4D,1,T,900,1500,60,PPA-,0,1,0,3,N,7,1"))
        # helmet, vest, shoes + the reserved 4th wire character
        self.assertIn(b",PAU-,", P.state("1A2B3C4D", 2, Command("T", 900, 1500, 60, "PAU")))

    def test_s_frame_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            P.state("1A2B3C4D", 1, Command("T", 900, 1500, 60, "PPA", True))    # alarm without V
        with self.assertRaises(ValueError):
            P.state("1A2B3C4D", 1, Command("T", 900, 1500, 60, fx="X"))
        with self.assertRaises(ValueError):
            P.state("1A2B3C4D", 1, Command("T", 2000, 1500, 60))

    def test_decoder_and_limits(self):
        d = P.LineDecoder()
        bodies, notes = d.feed(b"junk\n$PING,7*43\r\n$PING,7*44\n# hi\n")
        self.assertEqual((bodies, notes, d.bad_crc), (["PING,7"], ["junk", "# hi"], 1))
        L = P.DEFAULT_LIMITS
        self.assertEqual((L.tilt_floor(0), L.tilt_floor(1450), L.tilt_floor(900)), (1450, 1000, 1171))
        self.assertEqual(L.clamp(1600, 500), (1450, 1000))
        self.assertEqual((L.phome, L.thome), (900, 1800))
        # pan-dependent ceiling: 170 deg at hard right, 180 deg from the front on
        self.assertEqual([L.tilt_ceiling(p) for p in (0, 450, 900, 1450)], [1700, 1750, 1800, 1800])
        self.assertEqual(L.clamp(0, 1800), (0, 1700))

    def test_lcd_mirror_frame(self):
        r0, r1 = "Cek APD  ID:3".ljust(16), "H:OK R:NO S:??".ljust(16)
        self.assertEqual(P.parse(f"LCD,{r0}|{r1}"), ("LCD", (r0, r1)))
        r0 = "Halo, juga! :)".ljust(16)                     # commas inside the text
        self.assertEqual(P.parse(f"LCD,{r0}|{r1}"), ("LCD", (r0, r1)))
        self.assertEqual(P.parse("LCD,short|x")[0], "UNKNOWN")

    def test_lim_frames_old_and_new(self):
        kind, lim = P.parse("LIM,0,900,1450,1450,1000,1800,1800,120,90,400,300,1700,1")
        self.assertEqual((kind, lim.tmaxr, lim.calibrated), ("LIM", 1700, True))
        kind, lim = P.parse("LIM,0,900,1450,1450,1000,1250,1800,120,90,400,300,0")
        self.assertEqual((kind, lim.tmaxr, lim.calibrated), ("LIM", 1800, False))


class GeometryTests(unittest.TestCase):
    def test_round_trip_and_directions(self):
        m = CameraModel(hfov_deg=52, vfov_deg=88)
        for px, py in [(300, 500), (50, 900), (600, 100)]:
            a = m.to_angles(px, py, 648, 1152, 900, 1800)
            b = m.to_pixel(*a, 648, 1152, 900, 1800)
            self.assertAlmostEqual(b[0], px, places=6)
            self.assertAlmostEqual(b[1], py, places=6)
        self.assertLess(m.to_angles(648, 576, 648, 1152, 900, 1800)[0], 900)   # right -> smaller pan
        self.assertLess(m.to_angles(324, 1152, 648, 1152, 900, 1800)[1], 1800)  # below -> look down


class BrainTests(unittest.TestCase):
    def test_standing_person_with_jitter_does_not_move_camera(self):
        import random
        random.seed(1)
        tr, br = Tracker(), Brain(P.DEFAULT_LIMITS)
        changes, last = 0, None
        for i in range(80):
            jx, jy = random.uniform(-20, 20), random.uniform(-15, 15)
            t = 10 + 0.25 * i
            tr.update([det((860 + jx, 1500 + jy, 960 + jx, 1100 + jy))], t)
            cmd, _ = br.step(t, tr.visible(t, 0.4), pose=br.aim)
            changes += last is not None and (cmd.pan, cmd.tilt) != last
            last = (cmd.pan, cmd.tilt)
        self.assertEqual(changes, 0)

    def test_walking_person_is_followed(self):
        tr, br = Tracker(), Brain(P.DEFAULT_LIMITS)
        for i in range(40):
            t, x = 10 + 0.25 * i, 900 - 25 * i
            tr.update([det((x - 50, 1500, x + 50, 1100))], t)
            cmd, _ = br.step(t, tr.visible(t, 0.4), pose=br.aim)
        self.assertLess(abs(cmd.pan - x), 150)

    def test_patrol_route_is_left_right_left_right_left_centre(self):
        br = Brain(P.DEFAULT_LIMITS)
        route = br._patrol_route()
        pans = [p for p, _ in route]
        self.assertEqual(len(route), 6)
        self.assertTrue(pans[0] > 900 and pans[1] < 900 and pans[2] > 900 and pans[3] < 900 and pans[4] > 900)
        self.assertEqual(pans[5], 900)
        for p, t in route:                      # every stop is reachable inside the zone
            self.assertEqual(P.DEFAULT_LIMITS.clamp(p, t), (p, t))


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.tr = Tracker()
        self.tr.update([det((860, 1500, 960, 1100))], 10.0)
        self.track = self.tr.visible(10.0)[0]

    def hand(self, gesture):
        return Hand(gesture, 0.9, (150, 300, 200, 360), (175, 360))

    def run_frames(self, ix, gesture, start, n=2, step=0.25):
        out = None
        for k in range(n):
            out = ix.update(start + k * step, [self.track], {self.track.tid: [self.hand(gesture)]})
        return out

    def test_thumbs_up_nods_with_5s_cooldown(self):
        ix = Interaction()
        fx, fid = self.run_frames(ix, "Thumb_Up", 10.0)
        self.assertEqual(fx, "N")
        ix.update(10.6, [self.track], {})                          # hand down
        fx2, fid2 = self.run_frames(ix, "Thumb_Up", 11.0)
        self.assertEqual(fid2, fid)                                # cooldown: no second nod
        ix.update(12.0, [self.track], {})
        fx3, fid3 = self.run_frames(ix, "Thumb_Up", 10.0 + NOD_COOLDOWN + 0.5)
        self.assertNotEqual(fid3, fid)

    def test_violator_thumbs_up_gets_one_shake(self):
        for _ in range(5):                                         # helmet confirmed ABSENT
            self.tr.update([dict(det((860, 1500, 960, 1100)), evidence={"helmet": ("ABSENT", 0.9, "MODEL")})], 10.0)
        self.track = self.tr.visible(10.0)[0]
        self.assertEqual(self.track.state(), "VIOLATION")
        ix = Interaction()
        fx, fid = self.run_frames(ix, "Thumb_Up", 10.0)
        self.assertEqual(fx, "H")
        ix.update(11.0, [self.track], {})
        _, fid2 = self.run_frames(ix, "Thumb_Up", 12.0)
        self.assertEqual(fid2, fid)                                # "no" only once
        _, fid3 = self.run_frames(ix, "Open_Palm", 13.0)
        self.assertEqual(fid3, fid)                                # no greeting for a violator

    def test_open_palm_greets(self):
        ix = Interaction()
        fx, _ = self.run_frames(ix, "Open_Palm", 10.0)
        self.assertEqual(fx, "W")

    def test_single_frame_flicker_is_ignored(self):
        ix = Interaction()
        _, fid = self.run_frames(ix, "Thumb_Up", 10.0, n=1)
        self.assertEqual(fid, 0)


class OrientTests(unittest.TestCase):
    @staticmethod
    def person(rot):
        """Keypoints of an upright person as seen in a frame needing `rot` more degrees."""
        from sentinel.types import Keypoints
        ys = [100] * 5 + [200] * 2 + [250] * 4 + [300] * 2 + [400] * 4    # head < shoulder < hip
        pts = [(320.0, float(y)) for y in ys]
        if rot == 180:
            pts = [(x, 640.0 - y) for x, y in pts]
        elif rot in (90, 270):
            pts = [(y, 320.0) for x, y in pts]     # lying sideways: no vertical order
        return Keypoints(tuple(pts), tuple([0.9] * 17))

    def test_upright_score_signs(self):
        from sentinel.orient import upright_score
        self.assertGreater(upright_score([self.person(0)])[0], 0)
        self.assertLess(upright_score([self.person(180)])[0], 0)

    def test_needs_repeated_clear_votes(self):
        from sentinel.orient import AutoOrient
        ao = AutoOrient(votes_needed=3)
        flip = {0: (-15.0, 1), 90: (0.0, 0), 180: (17.0, 1), 270: (0.0, 0)}
        self.assertIsNone(ao.observe(0, flip))
        self.assertIsNone(ao.observe(4, flip))
        self.assertEqual(ao.observe(8, flip), 180)
        # a close call (margin too small) never votes
        close = {0: (10.0, 1), 90: (8.0, 1), 180: (-5.0, 1), 270: (0.0, 0)}
        for t in range(5):
            self.assertIsNone(ao.observe(20 + 4 * t, close))
        # nobody in view: no vote, no change
        empty = {r: (0.0, 0) for r in (0, 90, 180, 270)}
        self.assertIsNone(ao.observe(60, empty))


class ConfigTests(unittest.TestCase):
    def test_rig_config(self):
        cfg = json.loads((ROOT / "config/sentinel.json").read_text(encoding="utf-8"))
        self.assertIn(cfg["camera"]["rotate"], (0, 90, 180, 270))
        self.assertTrue(0 <= cfg["volume"] <= 100)


@unittest.skipUnless((ROOT / ".tools/ziglang-0.13.0/ziglang/zig.exe").exists() or shutil.which("cc"),
                     "no C compiler for the firmware core tests")
class FirmwareCoreTests(unittest.TestCase):
    def test_native_core_suite(self):
        import tempfile
        zig = ROOT / ".tools/ziglang-0.13.0/ziglang/zig.exe"
        cc = [str(zig), "cc"] if zig.exists() else [shutil.which("cc")]
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "core_tests.exe"
            build = subprocess.run(cc + ["-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-o", str(exe),
                                         str(ROOT / "tests/native/test_sentinel_core.c"),
                                         str(ROOT / "arduino/apd_sentinel/sentinel_core.c")],
                                   capture_output=True, text=True, timeout=600)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("ALL SENTINEL CORE TESTS PASSED", run.stdout)

    def test_full_scenario_on_simulated_mcu(self):
        """Brain + link + firmware core: patrol, lock, follow, group, alarm, fx, search,
        smart fans and LCD pacing (scripts/sentinel_hil.py --sim, ~75 s)."""
        run = subprocess.run([sys.executable, str(ROOT / "scripts/sentinel_hil.py"), "--sim"],
                             capture_output=True, text=True, timeout=400)
        self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])
        import re
        m = re.search(r"HASIL: (\d+)/(\d+) lulus", run.stdout)
        self.assertTrue(m and m.group(1) == m.group(2) and int(m.group(2)) >= 24, run.stdout[-1500:])


if __name__ == "__main__":
    unittest.main()
