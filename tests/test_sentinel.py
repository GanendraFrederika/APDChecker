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
from sentinel.interact import Interaction, InteractConfig, NOD_COOLDOWN  # noqa: E402
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
        frame = P.state("1A2B3C4D", 1, Command("T", 900, 1500, 60, "PPPA", False, 1, 0, 3, "N", 7, True))
        self.assertEqual(frame, b"$S,1A2B3C4D,1,T,900,1500,60,PPPA,0,1,0,3,N,7,1*21\n")
        # 3-item legacy items are padded with an unknown glove
        self.assertIn(b",PAU-,", P.state("1A2B3C4D", 2, Command("T", 900, 1500, 60, "PAU")))

    def test_s_frame_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            P.state("1A2B3C4D", 1, Command("T", 900, 1500, 60, "PPPA", True))   # alarm without V
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


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.tr = Tracker()
        self.tr.update([det((860, 1500, 960, 1100))], 10.0)
        self.track = self.tr.visible(10.0)[0]

    def hand(self, gesture, glove):
        return Hand(gesture, 0.9, (150, 300, 200, 360), (175, 360), glove, "COLOR")

    def run_frames(self, ix, gesture, glove, start, n=2, step=0.25):
        out = None
        for k in range(n):
            out = ix.update(start + k * step, [self.track], {self.track.tid: [self.hand(gesture, glove)]})
        return out

    def test_gloved_thumbs_up_nods_with_5s_cooldown(self):
        ix = Interaction()
        fx, fid = self.run_frames(ix, "Thumb_Up", "PRESENT", 10.0)
        self.assertEqual(fx, "N")
        ix.update(10.6, [self.track], {})                          # hand down
        fx2, fid2 = self.run_frames(ix, "Thumb_Up", "PRESENT", 11.0)
        self.assertEqual(fid2, fid)                                # cooldown: no second nod
        ix.update(12.0, [self.track], {})
        fx3, fid3 = self.run_frames(ix, "Thumb_Up", "PRESENT", 10.0 + NOD_COOLDOWN + 0.5)
        self.assertNotEqual(fid3, fid)

    def test_bare_hand_thumbs_up_shakes_once_then_alarms(self):
        ix = Interaction()
        fx, fid = self.run_frames(ix, "Thumb_Up", "ABSENT", 10.0)
        self.assertEqual(fx, "H")
        self.assertTrue(ix.glove_alarm(self.track.tid))
        ix.update(11.0, [self.track], {})
        _, fid2 = self.run_frames(ix, "Thumb_Up", "ABSENT", 12.0)
        self.assertEqual(fid2, fid)                                # "no" only once

    def test_debug_toggle_treats_bare_hands_as_gloved(self):
        ix = Interaction(InteractConfig(assume_gloves=True))
        fx, _ = self.run_frames(ix, "Thumb_Up", "ABSENT", 10.0)
        self.assertEqual(fx, "N")
        self.assertFalse(ix.glove_alarm(self.track.tid))

    def test_open_palm_greets(self):
        ix = Interaction()
        fx, _ = self.run_frames(ix, "Open_Palm", "UNKNOWN", 10.0)
        self.assertEqual(fx, "W")

    def test_single_frame_flicker_is_ignored(self):
        ix = Interaction()
        _, fid = self.run_frames(ix, "Thumb_Up", "PRESENT", 10.0, n=1)
        self.assertEqual(fid, 0)


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


if __name__ == "__main__":
    unittest.main()
