"""Synthetic source-generation tests only, not evidence of a C build."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from native_workshop_parity import generate_test,scenarios
from native_backend_vectors import generate_vectors, forward
from native_mcu_vectors import generate_test as generate_mcu_test

class NativeWorkshopGenerationTests(unittest.TestCase):
    def test_generated_parity_includes_workshop_and_fault_contract(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.c'
            count=generate_test(path)
            source=path.read_text()
            self.assertEqual(count,sum(len(seq) for seq in scenarios()))
            self.assertEqual(count,614)
            self.assertIn('f.camera_view_epoch=3',source)
            self.assertIn('f.camera_view_unstable=true',source)
            self.assertIn('WS_VEST',source)
            self.assertIn('APD_CAMERA_LOST',source)
            self.assertIn('WS_CACHED',source)
            self.assertIn('WS_NOT_VISIBLE',source)
            self.assertIn('UINT32_MAX',source)
            self.assertIn('assert(!ws_outputs_enabled())',source)
            self.assertNotIn('adb',source)
            self.assertNotIn('/dev/tty',source)

    def test_generating_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'a.c',Path(d)/'b.c'
            generate_test(a);generate_test(b)
            self.assertEqual(a.read_bytes(),b.read_bytes())

    def test_cli_explicit_missing_compiler_does_not_connect_board(self):
        spec=importlib.util.spec_from_file_location('native_core_cli',ROOT/'scripts/check_native_core.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with self.assertRaises(SystemExit):module.main(['--zig',str(ROOT/'NO_SUCH_COMPILER')])


class NativeBackendGenerationTests(unittest.TestCase):
    def test_known_clockwise_corner_rotation(self):
        self.assertEqual(forward([10,20,30,50],640,480,90),[430,10,460,30])
        self.assertEqual(forward([10,20,30,50],640,480,180),[610,430,630,460])
        self.assertEqual(forward([10,20,30,50],640,480,270),[20,610,50,630])

    def test_vectors_deterministic_no_io_drivers(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'a.c',Path(d)/'b.c'
            self.assertEqual(generate_vectors(a),1024)
            self.assertEqual(generate_vectors(b),1024)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            text=a.read_text()
            self.assertIn('apd_inverse_box',text)
            self.assertIn('apd_unletterbox_box',text)
            self.assertNotIn('rknn_init',text)
            self.assertNotIn('adb',text)
            self.assertNotIn('/dev/tty',text)


class NativeMCUGenerationTests(unittest.TestCase):
    def test_receiver_vectors_deterministic_and_offline(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'a.c',Path(d)/'b.c'
            self.assertEqual(generate_mcu_test(a),263)
            self.assertEqual(generate_mcu_test(b),263)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            source=a.read_text()
            self.assertIn('MCU_LINE_BYTES',source)
            self.assertIn('mcu_tick(&r,1800)',source)
            self.assertNotIn('/dev/tty',source)
            self.assertNotIn('Serial.write',source)

    def test_tracker_generator_checks_encoder_and_receiver(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.c';generate_test(path);source=path.read_text()
            self.assertIn('apd_mcu_encode_report',source)
            self.assertIn('mcu_feed',source)
            self.assertIn('receiver.alarm_on',source)
            self.assertIn('assert(wire[0]==0)',source)
