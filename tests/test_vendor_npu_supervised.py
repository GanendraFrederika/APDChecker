import unittest,sys,importlib.util
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'python'))
spec=importlib.util.spec_from_file_location('vendor_npu',ROOT/'scripts/test_luckfox_vendor_npu.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class VendorNpuOfflineTests(unittest.TestCase):
    def source(self):
        return '''[video.source]
enable_npu                     = 0
npu_fps=3
enable_ivs=0
enable_jpeg=0
enable_venc_1=0
enable_venc_2=0
[audio.0]
enable=0
[storage.0]
enable=0
[storage.1]
enable=0
[storage.2]
enable=0
[event.regional_invasion]
rockiva_model_type=small
'''
    def test_candidate_only_enables_shipped_npu(self):
        source=self.source();after=cli.candidate(source)
        self.assertEqual(after,source.replace('enable_npu                     = 0','enable_npu                     = 1'))
    def test_candidate_rejects_audio_recording_wrong_fps_or_model(self):
        for section,key,value in [('audio.0','enable','1'),('storage.1','enable','1'),
              ('video.source','npu_fps','0'),('event.regional_invasion','rockiva_model_type','big')]:
            bad=cli.change_key(self.source(),section,key,{'enable':'0','npu_fps':'3','rockiva_model_type':'small'}[key],value)
            with self.subTest(section=section,key=key):
                with self.assertRaises(ValueError):cli.candidate(bad)
    def test_duplicate_and_missing_key_rejected(self):
        for source in ('[x]\na=0\na=0\n','[x]\nb=0\n'):
            with self.assertRaises(ValueError):cli.change_key(source,'x','a','0','1')
    def test_other_section_not_modified(self):
        self.assertEqual(cli.change_key('[y]\na=0\n[x]\na=0\n','x','a','0','1'),'[y]\na=0\n[x]\na=1\n')
    def test_interrupt_parser_not_inference_fps(self):
        self.assertEqual(cli.irq_count(' 34:     146 GIC-0 141 Level ff660000.npu\n'),146)
        for bad in ('','34: -1 GIC-0 ff660000.npu','34: 10 20 GIC ff660000.npu','34: 10 GIC rga2'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):cli.irq_count(bad)
    def test_control_rejects_command_injection_or_unbounded_start(self):
        for command in ('reboot','start 301 78','start 60 79','start 60 78; reboot','start 60 78\n'):
            with patch.object(cli,'adb_output') as call:
                with self.assertRaises(ValueError):cli.control(Path('adb'),'known',command)
                call.assert_not_called()
    def test_missing_or_bad_exit_marker_rejected(self):
        for output in (b'PREVIEW_STARTED',b'APD_VENDOR_EXIT=12\n'):
            with patch.object(cli,'adb_output',return_value=output):
                with self.assertRaises(RuntimeError):cli.control(Path('adb'),'known','start 60 78')
    def test_no_persistent_config_or_boot_edit(self):
        source=(ROOT/'scripts/test_luckfox_vendor_npu.py').read_text(encoding='utf8')
        self.assertEqual(cli.CONFIG,'/tmp/apd-vendor-npu.ini')
        self.assertNotIn("'push','/userdata",source)
        for forbidden in ('killall','reboot','/dev/tty','rm -rf','mount -','echo mem'):
            self.assertNotIn(forbidden,source)

if __name__=='__main__':unittest.main()
