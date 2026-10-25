import importlib.util,sys,json,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'python'))
spec=importlib.util.spec_from_file_location('camera_supervised',ROOT/'scripts/test_luckfox_camera_supervised.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class SupervisedCameraRunnerTests(unittest.TestCase):
    def run_temp(self,arguments,control,subprocess_run=None):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cli,'ROOT',Path(tmp)), patch.object(sys,'argv',['camera']+arguments), patch.object(cli,'control',side_effect=control) as call:
                if subprocess_run:
                    with patch.object(cli.subprocess,'run',side_effect=subprocess_run):rc=cli.main()
                else:rc=cli.main()
            summaries=list(Path(tmp).glob('docs/luckfox/debug/supervised-camera/*/summary.json'))
            report=json.loads(summaries[0].read_text()) if summaries else None
            return rc,call.call_args_list,report
    def args(self):return ['--serial','known','--operator-supervised','--duration','30','--cutoff-c','78']
    def test_partial_start_error_still_stop_and_record(self):
        rc,calls,report=self.run_temp(self.args(),['CAMERA_IDLE',RuntimeError('ADB timeout'),'STOPPED','CAMERA_IDLE'])
        self.assertEqual(rc,2);self.assertEqual([c.args[2] for c in calls],['status','start','stop','status'])
        self.assertTrue(report['camera_stop_confirmed']);self.assertIn('ADB timeout',report['errors'])
        self.assertFalse(report['npu_load_test'])
    def test_refuse_takeover(self):
        rc,calls,report=self.run_temp(self.args(),['PREVIEW_PROCESS_RUNNING'])
        self.assertEqual(rc,2);self.assertEqual(len(calls),1);self.assertFalse(report['camera_stop_confirmed'])
    def test_forward_cleanup_timeout_still_writes_summary(self):
        effects=[subprocess.CompletedProcess([],0,stdout=''),subprocess.CompletedProcess([],0),subprocess.TimeoutExpired('adb',10)]
        rc,calls,report=self.run_temp(self.args()+['--view-stream'],['CAMERA_IDLE',RuntimeError('start timeout'),'STOPPED','CAMERA_IDLE'],effects)
        self.assertEqual(rc,2);self.assertTrue(report['camera_stop_confirmed'])
        self.assertTrue(any(e.startswith('forward cleanup') for e in report['errors']))
    def test_invalid_cutoff_rejected_before_control(self):
        with patch.object(sys,'argv',['camera','--serial','known','--operator-supervised','--cutoff-c','79']),patch.object(cli,'control') as call:
            with self.assertRaises(SystemExit) as ctx:cli.main()
            self.assertEqual(ctx.exception.code,2);call.assert_not_called()

if __name__=='__main__':unittest.main()
