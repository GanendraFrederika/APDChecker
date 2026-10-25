"""CLI uses mocked subprocess ONLY; no physical board access."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit_cli", ROOT / "scripts/audit_luckfox_thermal.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class ThermalCliTests(unittest.TestCase):
    def test_candidate_is_offline_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d, patch.object(cli.subprocess, "run") as run:
            target = Path(d)/"candidate.ini"
            args = ["candidate", "--source", str(ROOT / "docs/luckfox/debug/rkipc.ini.before-fps-test"),
                    "--fps", "3", "--output", str(target)]
            self.assertEqual(cli.main(args),0)
            self.assertIn("enable_npu = 0",target.read_text())
            with self.assertRaises(FileExistsError):
                cli.main(args)
            run.assert_not_called()

    def test_camera10_candidate_is_offline(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cli.subprocess,"run") as run:
            target=Path(directory)/"camera10.ini"
            self.assertEqual(cli.main(["candidate", "--source", str(ROOT / "docs/luckfox/debug/thermal-backup-20261011/rkipc.ini"), "--fps", "10", "--output", str(target)]),0)
            from apd_runtime.thermal_audit import parse_ini
            cfg=parse_ini(target.read_text())
            self.assertEqual(cfg.get("isp.0.adjustment","fps"),"10")
            run.assert_not_called()

    def test_wrong_board_never_reads_config_or_changes_files(self):
        with patch.object(cli, "adb_output", return_value=b"Nexus 4\x00") as adb:
            with self.assertRaises(RuntimeError):
                cli.main(["audit", "--serial", "mock-board", "--duration", "10"])
            self.assertEqual(adb.call_count,1)

    def test_static_shell_quoted_for_legacy_pty_not_host_shell(self):
        result = subprocess.CompletedProcess([],0,stdout=b"test",stderr=b"")
        with patch.object(cli.subprocess,"run",return_value=result) as run:
            self.assertEqual(cli.adb_output(Path("adb.exe"),"known",cli.SAMPLE),b"test")
            args = run.call_args
            self.assertEqual(args.args[0], ["adb.exe","-s","known","shell", "sh -c " + cli.shlex.quote(cli.SAMPLE)])
            self.assertNotIn("shell",args.kwargs)
            self.assertNotIn("input",args.kwargs)

    def test_hot_board_collects_one_sample_and_no_inventory_or_changes(self):
        raw = b"@@ uptime\n100 90\n@@ thermal\n72000\n@@ stat\ncpu 10 0 20 90 0 0 0 0\n@@ disk\n\n@@ memory\nMemFree: 20000 kB\n@@ rkipc\n123\n"
        with tempfile.TemporaryDirectory() as directory:
            fake_root = Path(directory)
            calls = []
            def fake(adb,serial,script):
                calls.append(script)
                if script == "cat /proc/device-tree/model\n":
                    return b"Luckfox Pico Mini B\x00\r\n"
                if script == "cat /userdata/rkipc.ini\n":
                    return b"[video.source]\nenable_npu=1\n"
                if script == cli.SAMPLE:
                    return raw
                raise AssertionError("unexpected board operation")
            with patch.object(cli,"ROOT",fake_root), patch.object(cli,"adb_output",side_effect=fake):
                self.assertEqual(cli.main(["audit","--serial","mock-board","--duration","10"]),2)
            self.assertEqual(len(calls),3)
            reports = list(fake_root.rglob("summary.json"))
            self.assertEqual(len(reports),1)
            import json
            report = json.loads(reports[0].read_text())
            self.assertFalse(report["changes_applied"])
            self.assertFalse(report["summary"]["thermal_safety_verified"])
            self.assertEqual(report["summary"]["samples"],1)
            self.assertFalse(list(fake_root.rglob("inventory.txt")))

    def test_cutoff_78_is_accepted_79_nonfinite_and_below_40_refused_before_adb(self):
        # Mock-only: accepted 78 proceeds to identity check, no hardware/files.
        with patch.object(cli, "adb_output", return_value=b"wrong-board") as adb:
            with self.assertRaises(RuntimeError):
                cli.main(["audit", "--serial", "mock", "--stop-at-c", "78"])
            self.assertEqual(adb.call_count, 1)
        for invalid in ("79", "39.9", "nan", "inf", "-inf"):
            with self.subTest(cutoff=invalid), patch.object(cli, "adb_output") as adb:
                with self.assertRaises(SystemExit) as exc:
                    cli.main(["audit", "--serial", "mock", "--stop-at-c=" + invalid])
                self.assertEqual(exc.exception.code, 2)
                adb.assert_not_called()

    def test_exact_78_ends_read_only_audit_without_inventory_or_shutdown(self):
        raw = b"@@ uptime\n100 90\n@@ thermal\n78000\n@@ stat\ncpu 10 0 20 90 0 0 0 0\n@@ disk\n\n@@ memory\nMemFree: 20000 kB\n@@ rkipc\n123\n"
        import json
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def fake(adb, serial, script):
                calls.append(script)
                if script == "cat /proc/device-tree/model\n":
                    return b"Luckfox Pico Mini B\x00\r\n"
                if script == "cat /userdata/rkipc.ini\n":
                    return b"[video.source]\nenable_npu=1\n"
                if script == cli.SAMPLE:
                    return raw
                raise AssertionError("unexpected device command")
            with patch.object(cli, "ROOT", Path(directory)), patch.object(cli, "adb_output", side_effect=fake):
                self.assertEqual(cli.main(["audit", "--serial", "mock", "--duration", "10", "--stop-at-c", "78"]), 2)
            reports = list(Path(directory).rglob("summary.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text())
            self.assertEqual(report["cutoff_c"], 78)
            self.assertIn("NOT auto-shutdown", report["stopped_reason"])
            self.assertFalse(report["changes_applied"])
            self.assertEqual(report["summary"]["samples"], 1)
            self.assertEqual(len(calls), 3)
