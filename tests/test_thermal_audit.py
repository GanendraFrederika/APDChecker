"""Synthetic/offline tests only: no ADB, camera, GPIO, or serial."""
from pathlib import Path
import unittest
from apd_runtime.thermal_audit import (blocks, cpu_counters, cpu_usage, disk_sectors,
    disk_delta, temperature, summarize, preview_candidate, parse_ini, camera_preview_candidate, idle_boot_candidate)

ROOT = Path(__file__).resolve().parents[1]


class ThermalAuditTests(unittest.TestCase):
    def test_cpu_excludes_guest_and_separates_iowait(self):
        before = cpu_counters("cpu 100 0 50 800 50 0 0 0 10 0")
        after = cpu_counters("cpu 130 0 70 840 60 0 0 0 25 0")
        self.assertEqual(cpu_usage(before, after), {"busy_percent": 50.0, "iowait_percent": 10.0})

    def test_cpu_reboot_or_no_progress_rejected(self):
        for a,b in [((10,5,0),(10,5,0)), ((10,5,0),(1,0,0)), ((10,5,0),(20,4,0))]:
            with self.assertRaises(ValueError):
                cpu_usage(a,b)

    def test_missing_cpu_rejected(self):
        with self.assertRaises(ValueError):
            cpu_counters("intr 1")

    def test_thermal_invalid_is_not_safe(self):
        self.assertEqual(temperature("70148"), 70.148)
        for raw in ("", "NaN", "inf", "999999"):
            with self.assertRaises(ValueError):
                temperature(raw)

    def test_disk_never_double_counts_partitions(self):
        data = "179 0 mmcblk0 1 0 10 0 1 0 20 0 0 0 0\n179 1 mmcblk0p1 1 0 10 0 1 0 20 0 0 0 0"
        self.assertEqual(disk_sectors(data), {"mmcblk0": (10,20)})
        self.assertEqual(disk_delta({"mmcblk0":(10,20)}, {"mmcblk0":(12,23)}),
                         {"mmcblk0":{"read_bytes":1024,"write_bytes":1536}})
        with self.assertRaises(ValueError):
            disk_delta({"mmcblk0":(10,20)}, {"mmcblk0":(9,20)})

    def test_no_sensor_never_claims_safety_or_fps(self):
        result = summarize([])
        self.assertIsNone(result["temperature_mean_c"])
        self.assertFalse(result["thermal_safety_verified"])
        self.assertIsNone(result["measured_camera_fps"])

    def test_blocks_crlf(self):
        self.assertEqual(blocks("@@ thermal\r\n58000\r\n@@ uptime\r\n10 9\r\n"),
                         {"thermal":"58000", "uptime":"10 9"})

    def test_preview_is_not_apd_ai_and_preserves_sensor_settings(self):
        raw = (ROOT / "docs/luckfox/debug/rkipc.ini.before-fps-test").read_bytes().decode()
        original = parse_ini(raw)
        for fps in (3,5):
            candidate = preview_candidate(raw,fps)
            cfg = parse_ini(candidate)
            self.assertEqual(cfg["video.source"]["enable_npu"], "0")
            self.assertEqual(cfg["video.source"]["enable_venc_1"], "0")
            self.assertEqual(cfg["video.0"]["dst_frame_rate_num"], str(fps))
            for section,key in [("video.0","src_frame_rate_num"), ("isp.0.adjustment","fps"),
                                ("video.0","width"),("video.0","buffer_size")]:
                self.assertEqual(cfg[section][key],original[section][key])
            self.assertIn("; available value:0 90 180 270",candidate)
            self.assertEqual(raw, (ROOT / "docs/luckfox/debug/rkipc.ini.before-fps-test").read_bytes().decode())

    def test_candidate_rejects_wrong_config_and_invalid_fps(self):
        raw = (ROOT / "docs/luckfox/debug/rkipc.ini.before-fps-test").read_bytes().decode()
        with self.assertRaises(ValueError):
            preview_candidate("[video.source]\nenable_npu=1\n",3)
        for fps in (True,1,10):
            with self.assertRaises(ValueError):
                preview_candidate(raw,fps)
        with self.assertRaises(ValueError):
            preview_candidate(raw.replace("enable_npu = 1", "enable_npu = 1\nenable_npu = 0"),3)

    def test_camera10_preserves_geometry_and_disables_unused_channels(self):
        raw=(ROOT / "docs/luckfox/debug/rkipc.ini.before-fps-test").read_text()
        cfg=parse_ini(camera_preview_candidate(raw)); old=parse_ini(raw)
        for section,key,value in [("video.0","src_frame_rate_num","10"),
                ("video.0","dst_frame_rate_num","10"),("video.0","gop","20"),
                ("isp.0.adjustment","fps","10"),("video.source","enable_npu","0"),
                ("audio.0","enable","0"),("video.source","enable_venc_1","0")]:
            self.assertEqual(cfg.get(section,key),value)
        for key in ("width","height","buffer_count","buffer_size","output_data_type"):
            self.assertEqual(cfg.get("video.0",key),old.get("video.0",key))
        self.assertEqual(cfg.get("isp.1.adjustment","fps"),old.get("isp.1.adjustment","fps"))
        for fps in (3,5,True,11):
            with self.assertRaises(ValueError):camera_preview_candidate(raw,fps)
        with self.assertRaises(ValueError):camera_preview_candidate("[video.0]\nwidth=1\n")

    def test_boot_idle_only_wraps_camera_launch(self):
        raw=(ROOT / "docs/luckfox/debug/thermal-backup-20261011/RkLunch.sh").read_text()
        result=idle_boot_candidate(raw)
        self.assertIn("if [ -f /userdata/apd-camera-idle ]; then",result)
        before=raw.split('\tif [ -d "/oem/usr/share/iqfiles" ];then')[0]
        self.assertTrue(result.startswith(before))
        self.assertTrue(result.endswith(raw[raw.index('\n}',len(before)):]))
        self.assertEqual(result.count('rkipc -a /oem/usr/share/iqfiles &'),1)
        with self.assertRaises(ValueError):idle_boot_candidate(result)
        with self.assertRaises(ValueError):idle_boot_candidate(raw.replace('rkipc &','other &'))
