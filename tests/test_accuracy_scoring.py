"""Scorer tests are synthetic HOST evidence, not model accuracy."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("score_apd_accuracy", ROOT / "scripts/score_apd_accuracy.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(n, truth="PRESENT", pred="PRESENT", mode="FRESH", **extra):
    result = dict(run_id="synthetic", scenario_id="D01", trial_id="trial1",
                  observation_id=str(n), item="helmet", ground_truth=truth,
                  prediction=pred, evidence_mode=mode,
                  unknown_reason="UNSEEN" if pred == "UNKNOWN" else "",
                  capture_ms="100", decision_ms="200")
    result.update(extra)
    return result


class AccuracyScoringTests(unittest.TestCase):
    def test_unknown_is_not_dropped_from_violation_recall(self):
        r = module.score_rows([row(1, "ABSENT", "ABSENT"), row(2, "ABSENT", "UNKNOWN", "NONE")])
        self.assertEqual(r["items"]["helmet"]["violation_recall_including_unknown_as_unresolved"], .5)
        self.assertEqual(r["items"]["helmet"]["observable_decision_coverage"], .5)
        self.assertFalse(r["production_ready"])

    def test_false_alarm_and_false_safe_separate(self):
        r = module.score_rows([row(1, "PRESENT", "ABSENT"), row(2, "ABSENT", "PRESENT")])["items"]["helmet"]
        self.assertEqual(r["false_alarm_on_visible_present"], 1)
        self.assertEqual(r["false_safe_on_visible_absent"], 1)
        self.assertEqual(r["violation_precision_observable_only"], 0)

    def test_unobservable_cached_not_automatically_called_error(self):
        r = module.score_rows([row(1, "UNOBSERVABLE", "PRESENT", "CACHED"), row(2, "UNOBSERVABLE", "ABSENT")])["items"]["helmet"]
        self.assertEqual(r["unobservable_known_by_evidence"], {"FRESH": 1, "CACHED": 1})
        self.assertIsNone(r["violation_precision_observable_only"])

    def test_latency_quantiles_and_missing_items(self):
        r = module.score_rows([row(1), row(2, decision_ms="400")])["items"]
        self.assertEqual(r["helmet"]["decision_latency_median_ms"], 200)
        self.assertEqual(r["helmet"]["decision_latency_p95_ms"], 300)
        self.assertEqual(r["vest"]["observations"], 0)
        self.assertIsNone(r["vest"]["correct_observable_fraction_unknown_not_dropped"])

    def test_empty_rejected(self):
        with self.assertRaises(ValueError): module.score_rows([])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError): module.score_rows([row(1), row(1)])

    def test_unknown_reason_required(self):
        with self.assertRaises(ValueError): module.score_rows([row(1, pred="UNKNOWN", mode="NONE", unknown_reason="")])

    def test_invalid_labels_rejected(self):
        for change in (dict(item="mask"), dict(prediction="SAFE"), dict(ground_truth="UNKNOWN"), dict(evidence_mode="GUESS")):
            with self.subTest(change=change), self.assertRaises(ValueError): module.score_rows([row(1, **change)])

    def test_missing_field_rejected(self):
        r = row(1); del r["scenario_id"]
        with self.assertRaises(ValueError): module.score_rows([r])

    def test_missing_identity_rejected(self):
        with self.assertRaises(ValueError): module.score_rows([row(1, trial_id="")])

    def test_timestamp_validation(self):
        for change in (dict(capture_ms="nan"), dict(decision_ms="inf"), dict(capture_ms="-1"), dict(decision_ms="50"), dict(decision_ms="")):
            with self.subTest(change=change), self.assertRaises(ValueError): module.score_rows([row(1, **change)])

    def test_known_without_evidence_rejected(self):
        with self.assertRaises(ValueError): module.score_rows([row(1, mode="NONE")])

    def test_distinct_items_and_trials_not_duplicates(self):
        r = module.score_rows([row(1), row(1, item="vest"), row(1, trial_id="trial2")])
        self.assertEqual(r["observation_item_count"], 3)
        self.assertEqual(r["trial_count"], 2)

    def test_all_unknown_does_not_report_perfect_accuracy(self):
        r = module.score_rows([row(1, pred="UNKNOWN", mode="NONE")])["items"]["helmet"]
        self.assertEqual(r["correct_observable_fraction_unknown_not_dropped"], 0)
        self.assertEqual(r["observable_decision_coverage"], 0)
