import copy
import json
from pathlib import Path
import tempfile
import unittest
from apd_runtime.config import load_config, verify_model
from apd_runtime.offline import replay


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_configuration_hardware_disabled(self):
        self.assertFalse(self.config['target']['deployment_enabled'])
        self.assertFalse(self.config['actuators']['enabled'])
        self.assertFalse(self.config['policy']['confirmed_by_operator'])

    def test_real_model_hashes(self):
        for spec in self.config['models'].values():
            self.assertTrue(verify_model(spec)[0].is_file())

    def test_hash_mismatch_rejected(self):
        spec = copy.deepcopy(self.config['models']['ppe'])
        spec['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            verify_model(spec)

    def test_enabling_hardware_rejected(self):
        for section, key in (('target', 'deployment_enabled'), ('actuators', 'enabled')):
            changed = copy.deepcopy(self.config)
            changed[section][key] = True
            with tempfile.TemporaryDirectory() as directory:
                file = Path(directory) / 'config.json'
                file.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_config(file)

    def test_replay_violation_fault_and_disabled_outputs(self):
        person = dict(label='person', confidence=0.9, box=[0,0,100,200])
        gear = dict(label='no_helmet', confidence=0.9, box=[10,10,40,35])
        rows = [dict(t=t, person=[person], ppe=[gear]) for t in (0,0.75,1.5)]
        rows.append(dict(t=2, fault='CAMERA_LOST'))
        report = replay(rows, self.config)
        self.assertEqual([r['alarm_indication'] for r in report], [False,False,True,False])
        self.assertTrue(all(not r['hardware_outputs_enabled'] for r in report))
        self.assertEqual(report[-1]['evidence']['observation'], 'CAMERA_LOST')

    def test_duplicate_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            replay([dict(t=0), dict(t=0)], self.config)

    def test_fake_safe_fault_rejected(self):
        with self.assertRaises(ValueError):
            replay([dict(t=0, fault='SAFE')], self.config)
