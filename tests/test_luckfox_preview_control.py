import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('preview_control',ROOT/'scripts/control_luckfox_preview.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class PreviewControlTests(unittest.TestCase):
    def test_wrong_board_sends_no_control(self):
        with patch.object(cli,'adb_output',return_value=b'Other board\0') as call:
            with self.assertRaises(RuntimeError): cli.control(Path('adb'),'known','stop')
            self.assertEqual(call.call_count,1)

    def test_missing_marker_is_not_success(self):
        with patch.object(cli,'adb_output',side_effect=[b'Luckfox Pico Mini B\0',b'PREVIEW_STARTED']):
            with self.assertRaises(RuntimeError):cli.control(Path('adb'),'known','start')

    def test_nonzero_remote_status_rejected(self):
        with patch.object(cli,'adb_output',side_effect=[b'Luckfox Pico Mini B\0',b'TOO_HOT_TO_START\nAPD_CONTROL_EXIT=12\n']):
            with self.assertRaises(RuntimeError):cli.control(Path('adb'),'known','start')

    def test_stop_success_no_hardware_protocols(self):
        with patch.object(cli,'adb_output',side_effect=[b'Luckfox Pico Mini B\0',b'PREVIEW_STOPPED\nAPD_CONTROL_EXIT=0\n']) as call:
            self.assertIn('PREVIEW_STOPPED',cli.control(Path('adb'),'known','stop'))
            script=call.call_args.args[2]
            self.assertIn('apd-previewctl.sh stop',script)
            for forbidden in ('GPIO','ttyS','reboot','RkLunch','rm '):self.assertNotIn(forbidden,script)

    def test_invalid_action_rejected_before_adb(self):
        with patch.object(cli,'adb_output') as call:
            with self.assertRaises(ValueError):cli.control(Path('adb'),'known','reboot')
            call.assert_not_called()

    def test_invalid_duration_before_board_access(self):
        for duration in (True, 9, 301, '60'):
            with patch.object(cli,'adb_output') as call:
                with self.assertRaises(ValueError):
                    cli.control(Path('adb'),'known','start',duration=duration)
                call.assert_not_called()

    def test_explicit_duration_sent_to_guard(self):
        with patch.object(cli,'adb_output',side_effect=[b'Luckfox Pico Mini B\0',b'PREVIEW_STARTED GUARDED\nAPD_CONTROL_EXIT=0\n']) as call:
            cli.control(Path('adb'),'known','start',duration=30)
            self.assertIn('apd-previewctl.sh start 30',call.call_args.args[2])

    def test_stop_cannot_have_custom_duration(self):
        with patch.object(cli,'adb_output') as call:
            with self.assertRaises(ValueError):cli.control(Path('adb'),'known','stop',duration=30)
            call.assert_not_called()


    def test_user_cutoff_78_explicit(self):
        with patch.object(cli,'adb_output',side_effect=[b'Luckfox Pico Mini B\0',b'APD_CONTROL_EXIT=0\n']) as call:
            cli.control(Path('adb'),'known','start',duration=300,cutoff_c=78)
            self.assertIn('start 300 78',call.call_args.args[2])

    def test_invalid_cutoff_before_adb(self):
        for cutoff in (True,39,79,100,'78'):
            with patch.object(cli,'adb_output') as call:
                with self.assertRaises(ValueError):cli.control(Path('adb'),'known','start',cutoff_c=cutoff)
                call.assert_not_called()
