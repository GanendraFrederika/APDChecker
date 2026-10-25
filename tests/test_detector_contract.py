"""Mock contract tests, not neural network accuracy/inference tests."""
from types import SimpleNamespace as NS
import sys
import unittest
from unittest.mock import Mock, patch
from apd_runtime.config import load_config
from apd_runtime.detector import HostDetector


class Array:
    def __init__(self, value):
        self.value = value
    def cpu(self):
        return self
    def tolist(self):
        return self.value


def result(names, labels=(), boxes=(), scores=()):
    return NS(names=names, boxes=NS(xyxy=Array(list(boxes)), cls=Array(list(labels)),
                                    conf=Array(list(scores))))


class DetectorContractTests(unittest.TestCase):
    def setup_detector(self, config=None, ppe_names=None, person_names=None):
        config = config or load_config()
        ppe_names = ppe_names if ppe_names is not None else dict(enumerate(config['models']['ppe']['expected_labels']))
        person_names = person_names if person_names is not None else {0: 'person', 1: 'bicycle'}
        ppe = Mock(names=ppe_names)
        ppe.names = ppe_names
        person = Mock()
        person.names = person_names
        fake_torch, fake_ultralytics = Mock(), Mock()
        fake_ultralytics.YOLO.side_effect = [ppe, person]
        with patch.dict(sys.modules, {'torch': fake_torch, 'ultralytics': fake_ultralytics}):
            detector = HostDetector(config)
        return detector, ppe, person, fake_torch, fake_ultralytics

    def test_cpu_limited_threads_and_sync_disabled(self):
        _, _, _, torch, ultra = self.setup_detector()
        torch.set_num_threads.assert_called_once_with(2)
        ultra.settings.update.assert_called_once_with({'sync': False, 'hub': False})

    def test_generic_model_as_ppe_rejected(self):
        with self.assertRaises(ValueError):
            self.setup_detector(ppe_names={0: 'person', 1: 'bicycle'})

    def test_production_vest_policy_rejected_by_current_model(self):
        config = load_config()
        config['policy']['required'] = ['vest', 'shoes', 'helmet']
        with self.assertRaisesRegex(ValueError, 'cannot support required policy'):
            self.setup_detector(config=config)

    def test_person_label_required(self):
        with self.assertRaises(ValueError):
            self.setup_detector(person_names={0: 'helmet'})

    def test_model_hash_checked_before_loading(self):
        config = load_config()
        config['models']['ppe']['sha256'] = '0'*64
        fake = Mock()
        with patch.dict(sys.modules, {'ultralytics': fake}), self.assertRaises(ValueError):
            HostDetector(config)
        fake.YOLO.assert_not_called()

    def test_aligned_detection_tensors_required(self):
        with self.assertRaises(ValueError):
            HostDetector._rows(result({0:'person'}, labels=[0], boxes=[], scores=[0.9]))

    def test_none_boxes_is_empty(self):
        self.assertEqual(HostDetector._rows(NS(boxes=None)), [])

    def test_inference_association_and_cpu(self):
        detector, ppe, person, _, _ = self.setup_detector()
        person.predict.return_value = [result(person.names, [0], [(0,0,100,200)], [0.9])]
        ppe.predict.return_value = [result(ppe.names, [2,3], [(10,10,40,35),(10,35,40,60)], [0.9,0.9])]
        report = detector.infer(NS(size=10))
        self.assertEqual(report['observation'], 'COMPLIANT')
        self.assertEqual(person.predict.call_args.kwargs['device'], 'cpu')
        self.assertEqual(person.predict.call_args.kwargs['classes'], [0])

    def test_model_capacity_fault(self):
        detector, ppe, person, _, _ = self.setup_detector()
        person.predict.return_value = [result(person.names, [0]*128, [(0,0,100,200)]*128, [0.9]*128)]
        ppe.predict.return_value = [result(ppe.names)]
        self.assertEqual(detector.infer(NS(size=10))['observation'], 'MODEL_ERROR')

    def test_empty_image_rejected(self):
        detector, _, _, _, _ = self.setup_detector()
        with self.assertRaises(ValueError):
            detector.infer(None)
