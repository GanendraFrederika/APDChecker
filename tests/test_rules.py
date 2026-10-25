import math
import unittest
from apd_runtime.rules import Detection as D, Debouncer, assess


def person(box=(0, 0, 100, 200), confidence=0.9):
    return D('person', confidence, box)


def head(label, box=(10, 10, 40, 35), confidence=0.9):
    return D(label, confidence, box)


class AssociationTests(unittest.TestCase):
    def test_no_people(self):
        self.assertEqual(assess([], [])['observation'], 'NO_PERSON')

    def test_generator_people_not_consumed_by_validation(self):
        self.assertEqual(assess((p for p in [person()]), [])['observation'], 'UNKNOWN')

    def test_missing_is_unknown(self):
        self.assertEqual(assess([person()], [])['observation'], 'UNKNOWN')

    def test_complete_required_only(self):
        self.assertEqual(assess([person()], [head('helmet'), head('mask')])['observation'], 'COMPLIANT')

    def test_explicit_violation(self):
        self.assertEqual(assess([person()], [head('no_helmet')])['observation'], 'VIOLATION')

    def test_no_global_credit(self):
        out = assess([person(), person((150, 0, 250, 200))], [head('helmet'), head('mask')])
        self.assertEqual(out['observation'], 'UNKNOWN')
        self.assertEqual([p['state'] for p in out['people']], ['COMPLIANT', 'UNKNOWN'])

    def test_overlapping_people_ambiguous(self):
        out = assess([person(), person((0, 0, 110, 200))], [head('helmet'), head('mask')])
        self.assertEqual(out['unassigned_equipment'], 2)
        self.assertTrue(all(p['state'] == 'UNKNOWN' for p in out['people']))

    def test_orphan_negative_is_not_a_violation(self):
        self.assertEqual(assess([], [head('no_helmet')])['observation'], 'UNKNOWN')

    def test_irrelevant_gear_does_not_poison_evidence(self):
        out = assess([person()], [head('helmet'), head('mask'), head('glove', (200, 0, 230, 30))])
        self.assertEqual(out['observation'], 'COMPLIANT')

    def test_head_region(self):
        out = assess([person()], [head('no_helmet', (10, 160, 40, 190))])
        self.assertEqual(out['observation'], 'UNKNOWN')

    def test_shoes_region(self):
        out = assess([person()], [head('shoes')], required=['shoes'])
        self.assertEqual(out['observation'], 'UNKNOWN')
        out = assess([person()], [head('shoes', (10, 170, 40, 195))], required=['shoes'])
        self.assertEqual(out['observation'], 'COMPLIANT')

    def test_low_confidence_negative_ignored(self):
        self.assertEqual(assess([person()], [head('no_helmet', confidence=0.2)])['observation'], 'UNKNOWN')

    def test_conflict_is_unknown(self):
        out = assess([person()], [head('helmet'), head('no_helmet'), head('mask')])
        self.assertEqual(out['observation'], 'UNKNOWN')
        self.assertEqual(out['people'][0]['conflicting_evidence'], ['helmet'])

    def test_other_explicit_violation_beats_conflict(self):
        out = assess([person()], [head('helmet'), head('no_helmet'), head('no_mask')])
        self.assertEqual(out['observation'], 'VIOLATION')

    def test_nan_equipment_not_safe(self):
        out = assess([person()], [head('helmet'), head('mask'), head('helmet', confidence=math.nan)])
        self.assertEqual(out['observation'], 'UNKNOWN')

    def test_invalid_person_not_empty_scene(self):
        out = assess([person((0, 0, 0, 200))], [])
        self.assertEqual(out['observation'], 'UNKNOWN')

    def test_bad_box_is_invalid(self):
        self.assertFalse(D('helmet', 0.9, None).valid())
        self.assertFalse(D('helmet', 0.9, (1, 2, 3)).valid())

    def test_required_validation(self):
        for required in ([], ['helmet', 'helmet'], ['scarf']):
            with self.subTest(required=required), self.assertRaises(ValueError):
                assess([], [], required)

    def test_vest_policy_registered_without_claiming_model_support(self):
        out = assess([person()], [head('vest', (20, 60, 80, 130))], required=['vest'])
        self.assertEqual(out['observation'], 'COMPLIANT')

    def test_label_normalization(self):
        self.assertEqual(assess([person()], [head('No-Helmet')])['observation'], 'VIOLATION')


class TemporalTests(unittest.TestCase):
    def confirmed(self):
        d = Debouncer()
        self.assertFalse(d.update('VIOLATION', 0))
        self.assertFalse(d.update('VIOLATION', 0.75))
        self.assertTrue(d.update('VIOLATION', 1.5))
        return d

    def test_confirmation(self):
        self.confirmed()

    def test_single_sample_and_stall_not_confirmed(self):
        d = Debouncer()
        self.assertFalse(d.update('VIOLATION', 0))
        self.assertFalse(d.update('VIOLATION', 10))

    def test_too_few_samples(self):
        d = Debouncer(max_gap=10)
        d.update('VIOLATION', 0)
        self.assertFalse(d.update('VIOLATION', 3))

    def test_unknown_retains_prior_indication(self):
        self.assertTrue(self.confirmed().update('UNKNOWN', 2))

    def test_unknown_resets_confirmation(self):
        d = Debouncer()
        d.update('VIOLATION', 0)
        d.update('UNKNOWN', 1)
        self.assertFalse(d.update('VIOLATION', 1.5))

    def test_clear_requires_debounce(self):
        d = self.confirmed()
        self.assertTrue(d.update('COMPLIANT', 2))
        self.assertTrue(d.update('COMPLIANT', 3.5))
        self.assertFalse(d.update('COMPLIANT', 5))

    def test_fault_clears_indication_not_compliance(self):
        for fault in ('CAMERA_LOST', 'MODEL_ERROR', 'STARTING'):
            with self.subTest(fault=fault):
                self.assertFalse(self.confirmed().update(fault, 2))

    def test_repeated_or_reversed_timestamp_rejected(self):
        d = Debouncer()
        d.update('VIOLATION', 1)
        for t in (1, 0, math.nan):
            with self.assertRaises(ValueError):
                d.update('VIOLATION', t)

    def test_invalid_state_rejected(self):
        with self.assertRaises(ValueError):
            Debouncer().update('SAFE', 0)

    def test_bad_timing_rejected(self):
        for params in ({'min_samples': 0}, {'max_gap': 0}, {'clear_seconds': -1}):
            with self.assertRaises(ValueError):
                Debouncer(**params)
