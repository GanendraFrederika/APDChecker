"""Synthetic view changes, not real servo/capture/identity accuracy tests."""
from dataclasses import replace
import json
import math
from pathlib import Path
import unittest
from apd_runtime.camera_view import CameraMotionGate, MotionSettings
from apd_runtime.rules import Detection as D
from apd_runtime.tracking import PersonPPETracker
from apd_runtime.tracking_offline import replay_tracking, load_workshop_config

PERSON = [D('person', .9, (0, 0, 100, 200))]
GEAR = [D('vest', .9, (20, 60, 80, 130)), D('shoes', .9, (10, 170, 90, 195)),
        D('helmet', .9, (10, 5, 60, 35))]


class CameraViewTrackingTests(unittest.TestCase):
    def setUp(self):
        self.t = PersonPPETracker()
        self.t.update(1, 0, PERSON, GEAR)
        self.prior = self.t.update(2, .3, PERSON, GEAR)
        self.assertEqual(self.prior['observation'], 'COMPLIANT')

    def test_new_view_same_boxes_cannot_inherit_ppe_or_identity(self):
        r = self.t.update(3, .6, PERSON, camera_view_epoch=1)
        self.assertEqual(r['observation'], 'UNKNOWN')
        self.assertNotEqual(r['people'][0]['track_id'], self.prior['people'][0]['track_id'])
        self.assertTrue(all(v is None for v in r['indicators']['lights'].values()))

    def test_new_view_requires_fresh_confirmation_even_if_returning_home(self):
        r = self.t.update(3, .6, PERSON, GEAR, camera_view_epoch=1)
        self.assertEqual(r['observation'], 'UNKNOWN')
        r = self.t.update(4, .9, PERSON, GEAR, camera_view_epoch=1)
        self.assertEqual(r['observation'], 'COMPLIANT')
        r = self.t.update(5, 1.2, PERSON, GEAR, camera_view_epoch=2)
        self.assertEqual(r['observation'], 'UNKNOWN')

    def test_moving_or_settling_suppresses_positive_and_negative(self):
        for i in range(3, 10):
            r = self.t.update(i, (i-1)*.3, PERSON,
                              [D('no_helmet', .9, (10, 5, 60, 35))],
                              visibility={0: {'helmet': 'OBSERVABLE'}},
                              camera_view_epoch=1, camera_view_unstable=True)
            self.assertEqual(r['observation'], 'STARTING')
            self.assertFalse(r['alarm_candidate'])
            self.assertEqual(self.t.tracks, {})
            self.assertTrue(all(v is None for v in r['indicators']['lights'].values()))
        r = self.t.update(10, 2.7, PERSON, GEAR, camera_view_epoch=1)
        self.assertEqual(r['observation'], 'UNKNOWN')

    def test_unstable_without_epoch_change_also_flushes(self):
        self.t.update(3, .6, PERSON, GEAR, camera_view_unstable=True)
        r = self.t.update(4, .9, PERSON, GEAR)
        self.assertEqual(r['observation'], 'UNKNOWN')
        self.assertNotEqual(r['people'][0]['track_id'], self.prior['people'][0]['track_id'])

    def test_begin_move_invalidates_even_without_an_inference_frame(self):
        r = self.t.invalidate_camera_view(1)
        self.assertEqual(r['observation'], 'STARTING')
        self.assertEqual(r['camera_view_epoch'], 1)
        self.assertEqual(self.t.tracks, {})
        self.assertFalse(r['alarm_candidate'])
        self.assertEqual(self.t.previous_frame_id, 2)

    def test_old_buffered_view_and_implicit_default_rejected(self):
        self.t.invalidate_camera_view(1)
        for kwargs in ({'camera_view_epoch': 0}, {}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.t.update(3, .6, PERSON, GEAR, **kwargs)
            self.assertEqual(self.t.tracks, {})

    def test_fault_has_priority_over_unstable(self):
        r = self.t.update(3, .6, camera_view_epoch=1, camera_view_unstable=True,
                          fault='CAMERA_LOST')
        self.assertEqual(r['observation'], 'CAMERA_LOST')

    def test_invalid_epoch_or_boolean_flushes(self):
        for value in (True, -1, .5, None, 2**64):
            with self.subTest(epoch=value), self.assertRaises(ValueError):
                self.t.update(3, .6, PERSON, GEAR, camera_view_epoch=value)
            self.assertEqual(self.t.tracks, {})
        for value in (0, 1, 'false', None):
            with self.subTest(unstable=value), self.assertRaises(ValueError):
                self.t.update(3, .6, PERSON, GEAR, camera_view_unstable=value)

    def test_invalidation_requires_strictly_newer_epoch(self):
        self.t.invalidate_camera_view(2)
        for value in (0, 1, 2, True, 2**64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.t.invalidate_camera_view(value)

    def test_frame_order_checks_not_reset_by_movement(self):
        self.t.invalidate_camera_view(1)
        with self.assertRaises(ValueError):
            self.t.update(2, .6, PERSON, GEAR, camera_view_epoch=1)

    def test_motion_replay_is_forwarded_and_always_non_actuating(self):
        rows = [json.loads(s) for s in (Path(__file__).parent / 'fixtures' /
                'apd_camera_motion_replay.jsonl').read_text().splitlines()]
        rs = replay_tracking(rows, load_workshop_config())
        self.assertEqual(len(rs), 16)
        self.assertEqual(rs[1]['observation'], 'COMPLIANT')
        for i in (2, 3, 10):
            self.assertEqual(rs[i]['observation'], 'STARTING')
        for i in (4, 5, 7, 8, 11, 14):
            self.assertEqual(rs[i]['observation'], 'UNKNOWN')
        self.assertEqual(rs[13]['observation'], 'CAMERA_LOST')
        self.assertTrue(all(not r['hardware_outputs_enabled'] for r in rs))


class CameraMotionGateTests(unittest.TestCase):
    def setUp(self):
        self.t = PersonPPETracker()
        self.g = CameraMotionGate(self.t)

    def test_fixed_view_default_and_no_io(self):
        v = self.g.snapshot(0)
        self.assertEqual(v.state, 'STABLE')
        self.assertEqual(v.camera_view_epoch, 0)
        self.assertFalse(v.hardware_outputs_enabled)

    def test_move_ack_settle_reacquire_end_to_end(self):
        self.t.update(1, 0, PERSON, GEAR)
        self.t.update(2, .3, PERSON, GEAR)
        r = self.g.begin_move(.4)
        self.assertEqual(r['observation'], 'STARTING')
        v = self.g.snapshot(.6)
        self.assertEqual(v.state, 'MOVING')
        r = self.t.update(3, .6, PERSON, GEAR, **v.tracker_kwargs())
        self.assertEqual(r['observation'], 'STARTING')
        self.g.acknowledge_motion_complete(1, .7)
        self.assertEqual(self.g.snapshot(1.699).state, 'SETTLING')
        v = self.g.snapshot(1.7)
        self.assertEqual(v.state, 'STABLE')
        r = self.t.update(4, 1.7, PERSON, GEAR, **v.tracker_kwargs())
        self.assertEqual(r['observation'], 'UNKNOWN')
        r = self.t.update(5, 2, PERSON, GEAR, **v.tracker_kwargs())
        self.assertEqual(r['observation'], 'COMPLIANT')
        self.assertEqual(r['people'][0]['track_id'], 2)

    def test_no_ack_times_out_without_automatic_recovery(self):
        self.g.begin_move(0)
        self.assertEqual(self.g.snapshot(2.999).state, 'MOVING')
        v = self.g.snapshot(3)
        self.assertEqual(v.state, 'FAULT')
        self.assertTrue(v.camera_view_unstable)
        self.assertEqual(v.reason, 'MOVEMENT_TIMEOUT')
        self.assertEqual(self.g.snapshot(100).state, 'FAULT')

    def test_ack_at_exact_deadline_cannot_unlock(self):
        self.g.begin_move(0)
        with self.assertRaises(ValueError):
            self.g.acknowledge_motion_complete(1, 3)
        self.assertEqual(self.g.state, 'FAULT')

    def test_stale_or_duplicate_ack_fails_closed(self):
        for epoch in (0, 2, True):
            with self.subTest(epoch=epoch):
                self.setUp(); self.g.begin_move(0)
                with self.assertRaises(ValueError):
                    self.g.acknowledge_motion_complete(epoch, .2)
                self.assertTrue(self.g.snapshot(.3).camera_view_unstable)
        self.setUp(); self.g.begin_move(0)
        self.g.acknowledge_motion_complete(1, .2)
        with self.assertRaises(ValueError):
            self.g.acknowledge_motion_complete(1, .3)
        self.assertEqual(self.g.state, 'FAULT')

    def test_no_move_queue_and_no_auto_retry(self):
        self.g.begin_move(0)
        with self.assertRaises(ValueError):
            self.g.begin_move(.1)
        self.assertEqual(self.g.state, 'FAULT')
        with self.assertRaises(ValueError):
            self.g.begin_move(10)
        self.assertEqual(self.g.state, 'FAULT')

    def test_explicit_pose_verified_recovery_gets_new_view_then_settles(self):
        self.g.begin_move(0)
        old_epoch = self.g.snapshot(3).camera_view_epoch
        r = self.g.recover_after_pose_verified(3.1)
        self.assertEqual(r['observation'], 'STARTING')
        self.assertGreater(r['camera_view_epoch'], old_epoch)
        self.assertTrue(self.g.snapshot(3.2).camera_view_unstable)
        self.assertFalse(self.g.snapshot(4.1).camera_view_unstable)

    def test_invalid_or_backwards_clock_flushes_and_faults(self):
        for value in (True, -1, math.nan, math.inf, None):
            with self.subTest(value=value):
                self.setUp()
                with self.assertRaises(ValueError):
                    self.g.snapshot(value)
                self.assertEqual(self.g.state, 'FAULT')
        self.setUp(); self.g.snapshot(10)
        with self.assertRaises(ValueError):
            self.g.snapshot(9)
        self.assertEqual(self.g.state, 'FAULT')

    def test_saved_capture_metadata_immutable_after_later_move(self):
        old = self.g.snapshot(0)
        self.g.begin_move(.1)
        with self.assertRaises(ValueError):
            self.t.update(1, .2, PERSON, GEAR, **old.tracker_kwargs())

    def test_invalid_settings(self):
        for value in (True, 0, -1, math.nan, 61):
            for field in ('settle_seconds', 'movement_timeout_seconds'):
                with self.subTest(value=value, field=field), self.assertRaises(ValueError):
                    replace(MotionSettings(), **{field: value})
