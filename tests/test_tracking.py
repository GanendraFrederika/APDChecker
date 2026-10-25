"""Synthetic detections only: tests logic, NOT tracker/model field accuracy."""
import copy
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
import unittest
from apd_runtime.rules import Detection as D
from apd_runtime.tracking import PersonPPETracker, TrackingSettings, model_capabilities, INDICATOR_COLORS
from apd_runtime.tracking_offline import load_workshop_config, replay_tracking
from apd_runtime.config import load_config


def person(x=0, confidence=0.9):
    return D('person', confidence, (x, 0, x+100, 200))


def gear(kind, x=0, negative=False, confidence=0.9):
    boxes = {'vest': (20,60,80,130), 'shoes': (10,170,90,195), 'helmet': (10,5,60,35)}
    a,b,c,d = boxes[kind]
    return D(('no_' if negative else '')+kind, confidence, (x+a,b,x+c,d))


def complete(x=0):
    return [gear(k,x) for k in ('vest','shoes','helmet')]


def visibility(**items):
    return {0: items}


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tracker = PersonPPETracker()
        self.frame = 0

    def update(self, t, equipment=(), people=None, **kwargs):
        self.frame += 1
        return self.tracker.update(self.frame, t, [person()] if people is None else people, equipment, **kwargs)

    def confirmed_present(self):
        self.update(0, complete())
        return self.update(0.3, complete())

    def confirmed_absent(self, kind='helmet'):
        output = None
        for t in (0,0.5,1,1.5):
            output = self.update(t, [gear(kind, negative=True)], visibility=visibility(**{kind:'OBSERVABLE'}))
        return output

    def test_policy_and_colors(self):
        self.assertEqual(self.tracker.settings.required, ('vest','shoes','helmet'))
        self.assertEqual(INDICATOR_COLORS, {'vest':'green','shoes':'yellow','helmet':'red'})

    def test_empty_scene(self):
        report = self.update(0, people=[])
        self.assertEqual(report['observation'], 'NO_PERSON')
        self.assertFalse(report['alarm_candidate'])
        self.assertEqual(report['indicators']['mode'], 'NO_PERSON')

    def test_one_frame_never_confirms_positive_or_alarm(self):
        report = self.update(0, complete())
        self.assertEqual(report['observation'], 'UNKNOWN')
        self.assertTrue(all(v is None for v in report['indicators']['lights'].values()))
        self.assertFalse(report['alarm_candidate'])

    def test_complete_person_all_three_lights(self):
        report = self.confirmed_present()
        self.assertEqual(report['observation'], 'COMPLIANT')
        self.assertEqual(report['indicators']['lights'], {'vest':True,'shoes':True,'helmet':True})
        self.assertFalse(report['alarm_candidate'])

    def test_stationary_track_id_stable(self):
        a = self.update(0, complete())
        b = self.update(0.3, complete())
        self.assertEqual(a['people'][0]['track_id'], b['people'][0]['track_id'])

    def test_walking_person_track_id_stable(self):
        a = self.update(0, complete(0), [person(0)])
        b = self.update(0.3, complete(15), [person(15)])
        self.assertEqual(a['people'][0]['track_id'], b['people'][0]['track_id'])
        self.assertEqual(b['observation'], 'COMPLIANT')

    def test_feet_never_visible_not_absent(self):
        for t in (0,0.5,1,1.5):
            out = self.update(t, [gear('vest'),gear('helmet')], visibility=visibility(shoes='NOT_VISIBLE'))
        self.assertEqual(out['people'][0]['items']['shoes']['state'], 'UNKNOWN')
        self.assertEqual(out['people'][0]['items']['shoes']['reason'], 'NOT_VISIBLE')
        self.assertFalse(out['alarm_candidate'])

    def test_visible_but_detector_misses_shoes_not_absent(self):
        for t in (0,0.5,1,1.5):
            out = self.update(t, [gear('vest'),gear('helmet')], visibility=visibility(shoes='OBSERVABLE'))
        self.assertEqual(out['people'][0]['items']['shoes']['state'], 'UNKNOWN')
        self.assertFalse(out['alarm_candidate'])

    def test_unverified_negative_does_not_confirm(self):
        for t in (0,0.5,1,1.5):
            out = self.update(t, [gear('shoes', negative=True)])
        item = out['people'][0]['items']['shoes']
        self.assertEqual(item['state'], 'UNKNOWN')
        self.assertEqual(item['reason'], 'NEGATIVE_VISIBILITY_UNVERIFIED')
        self.assertFalse(out['alarm_candidate'])

    def test_negative_for_hidden_region_ignored(self):
        for t in (0,0.5,1,1.5):
            out = self.update(t, [gear('helmet', negative=True)], visibility=visibility(helmet='NOT_VISIBLE'))
        self.assertFalse(out['alarm_candidate'])
        self.assertEqual(out['people'][0]['items']['helmet']['state'], 'UNKNOWN')

    def test_negative_requires_time_and_sample_count(self):
        visible = visibility(helmet='OBSERVABLE')
        for t in (0,0.5,1):
            out = self.update(t, [gear('helmet', negative=True)], visibility=visible)
            self.assertFalse(out['alarm_candidate'])
        out = self.update(1.5, [gear('helmet', negative=True)], visibility=visible)
        self.assertTrue(out['alarm_candidate'])
        self.assertEqual(out['people'][0]['items']['helmet']['state'], 'ABSENT')
        self.assertFalse(out['indicators']['lights']['helmet'])

    def test_independent_item_can_confirm_while_other_item_unknown(self):
        out = self.confirmed_absent('shoes')
        self.assertTrue(out['alarm_candidate'])
        self.assertEqual(out['people'][0]['items']['helmet']['state'], 'UNKNOWN')

    def test_cached_positive_with_partial_occlusion(self):
        self.confirmed_present()
        out = self.update(0.6, [gear('vest'),gear('helmet')], visibility=visibility(shoes='NOT_VISIBLE'))
        shoes = out['people'][0]['items']['shoes']
        self.assertEqual(shoes['state'], 'PRESENT')
        self.assertEqual(shoes['source'], 'CACHED')
        self.assertEqual(shoes['observed_at'], 0.3)
        self.assertEqual(shoes['reason'], 'NOT_VISIBLE')
        self.assertTrue(out['indicators']['lights']['shoes'])

    def test_cache_expiry_without_frame_gap(self):
        self.confirmed_present()
        for t in (0.6,1.1,1.6,2.1,2.31):
            out = self.update(t, [gear('vest'),gear('helmet')])
        self.assertEqual(out['people'][0]['items']['shoes']['state'], 'UNKNOWN')
        self.assertIsNone(out['indicators']['lights']['shoes'])
        self.assertFalse(out['alarm_candidate'])

    def test_cache_reuse_does_not_extend_expiry(self):
        self.confirmed_present()
        out = self.update(0.6)
        out2 = self.update(0.9)
        self.assertEqual(out['people'][0]['items']['shoes']['expires_at'], 2.3)
        self.assertEqual(out2['people'][0]['items']['shoes']['expires_at'], 2.3)

    def test_cached_negative_cannot_drive_alarm_without_fresh_negative(self):
        self.confirmed_absent()
        out = self.update(1.8)
        self.assertEqual(out['people'][0]['items']['helmet']['state'], 'ABSENT')
        self.assertEqual(out['people'][0]['items']['helmet']['source'], 'CACHED')
        self.assertFalse(out['alarm_candidate'])

    def test_item_removed_invalidates_old_positive_immediately(self):
        self.confirmed_present()
        out = self.update(0.6,[gear('helmet', negative=True)],visibility=visibility(helmet='OBSERVABLE'))
        item = out['people'][0]['items']['helmet']
        self.assertEqual(item['state'], 'UNKNOWN')
        self.assertEqual(item['candidate'], 'ABSENT')
        self.assertFalse(out['alarm_candidate'])

    def test_item_put_on_invalidates_old_negative_immediately(self):
        self.confirmed_absent()
        out = self.update(1.8,[gear('helmet')])
        self.assertEqual(out['people'][0]['items']['helmet']['state'], 'UNKNOWN')
        self.assertFalse(out['alarm_candidate'])
        out = self.update(2.1,[gear('helmet')])
        self.assertEqual(out['people'][0]['items']['helmet']['state'], 'PRESENT')

    def test_remove_then_put_on_each_item_in_same_track(self):
        for kind in ('vest','shoes','helmet'):
            with self.subTest(kind=kind):
                self.setUp()
                initial=self.confirmed_present()
                tid=initial['people'][0]['track_id']
                remaining=[gear(k) for k in ('vest','shoes','helmet') if k != kind]
                negative=remaining+[gear(kind,negative=True)]
                visible=visibility(**{kind:'OBSERVABLE'})
                changed=self.update(0.6,negative,visibility=visible)
                item=changed['people'][0]['items'][kind]
                self.assertEqual(item['state'],'UNKNOWN')
                self.assertEqual(item['transition'],{'previous':'PRESENT','current':'UNKNOWN','cause':'OPPOSING_EVIDENCE'})
                self.assertFalse(changed['alarm_candidate'])
                for t in (0.9,1.2,1.5,1.8,2.2):
                    changed=self.update(t,negative,visibility=visible)
                self.assertEqual(changed['people'][0]['track_id'],tid)
                self.assertEqual(changed['people'][0]['items'][kind]['state'],'ABSENT')
                self.assertEqual(changed['people'][0]['items'][kind]['transition']['cause'],'NEGATIVE_CONFIRMED')
                self.assertTrue(changed['alarm_candidate'])
                putting_on=self.update(2.5,complete())
                self.assertEqual(putting_on['people'][0]['items'][kind]['state'],'UNKNOWN')
                self.assertFalse(putting_on['alarm_candidate'])
                restored=self.update(2.8,complete())
                self.assertEqual(restored['people'][0]['track_id'],tid)
                self.assertEqual(restored['observation'],'COMPLIANT')
                self.assertEqual(restored['people'][0]['items'][kind]['transition']['cause'],'POSITIVE_CONFIRMED')
                self.assertTrue(all(restored['indicators']['lights'].values()))

    def test_removed_item_without_negative_evidence_expires_to_unknown_not_alarm(self):
        self.confirmed_present()
        remaining=[gear('vest'),gear('shoes')]
        for t in (0.6,1.1,1.6,2.1,2.4):
            changed=self.update(t,remaining,visibility=visibility(helmet='OBSERVABLE'))
        item=changed['people'][0]['items']['helmet']
        self.assertEqual(item['state'],'UNKNOWN')
        self.assertEqual(item['transition']['cause'],'EVIDENCE_EXPIRED')
        self.assertFalse(changed['alarm_candidate'])

    def test_unchanged_state_has_no_repeated_transition_event(self):
        self.confirmed_present()
        out=self.update(0.6,complete())
        self.assertTrue(all(item['transition'] is None for item in out['people'][0]['items'].values()))

    def test_conflicting_item_discards_cache(self):
        self.confirmed_present()
        out = self.update(0.6,[gear('helmet'),gear('helmet', negative=True)],visibility=visibility(helmet='OBSERVABLE'))
        self.assertEqual(out['people'][0]['items']['helmet']['state'], 'UNKNOWN')
        self.assertEqual(out['people'][0]['items']['helmet']['reason'], 'CONFLICTING_DETECTIONS')
        self.assertFalse(out['alarm_candidate'])

    def test_conflict_does_not_hide_other_explicit_negative(self):
        equipment = [gear('helmet'),gear('helmet',negative=True),gear('shoes',negative=True)]
        for t in (0,0.5,1,1.5):
            out = self.update(t,equipment,visibility=visibility(helmet='OBSERVABLE',shoes='OBSERVABLE'))
        self.assertTrue(out['alarm_candidate'])
        self.assertEqual(out['people'][0]['items']['helmet']['state'], 'UNKNOWN')

    def test_unknown_interrupts_unconfirmed_negative_streak(self):
        v = visibility(helmet='OBSERVABLE')
        self.update(0,[gear('helmet',negative=True)],visibility=v)
        self.update(0.5,[gear('helmet',negative=True)],visibility=v)
        self.update(1)
        out = self.update(1.5,[gear('helmet',negative=True)],visibility=v)
        self.assertFalse(out['alarm_candidate'])
        self.assertEqual(out['people'][0]['items']['helmet']['candidate_samples'],1)

    def test_too_few_samples_even_if_elapsed_time_sufficient(self):
        self.tracker = PersonPPETracker(replace(TrackingSettings(), absent_samples=8))
        out = self.confirmed_absent()
        self.assertFalse(out['alarm_candidate'])

    def test_long_inference_gap_flushes_cache_and_candidates(self):
        prior = self.confirmed_present()['people'][0]['track_id']
        out = self.update(2,complete())
        self.assertNotEqual(prior,out['people'][0]['track_id'])
        self.assertEqual(out['observation'],'UNKNOWN')

    def test_one_missed_person_frame_discards_evidence(self):
        prior = self.confirmed_present()['people'][0]['track_id']
        self.update(0.6,people=[])
        out = self.update(0.9)
        self.assertEqual(prior,out['people'][0]['track_id'])
        self.assertEqual(out['observation'],'UNKNOWN')

    def test_expired_lost_track_reentry_gets_new_id(self):
        prior = self.confirmed_present()['people'][0]['track_id']
        self.update(0.6,people=[])
        self.update(1.1,people=[])
        out = self.update(1.6)
        self.assertNotEqual(prior,out['people'][0]['track_id'])
        self.assertEqual(out['observation'],'UNKNOWN')

    def test_different_people_cannot_accumulate_negative_streak(self):
        for i,t in enumerate((0,0.5,1,1.5)):
            x=i*200
            out=self.update(t,[gear('helmet',x,negative=True)],[person(x)],visibility=visibility(helmet='OBSERVABLE'))
            self.assertFalse(out['alarm_candidate'])
            self.assertEqual(out['people'][0]['items']['helmet']['candidate_samples'],1)

    def test_detection_order_change_preserves_track_evidence(self):
        a=self.update(0,[gear('vest'),gear('helmet',200)],[person(),person(200)])
        b=self.update(0.3,[gear('vest'),gear('helmet',200)],[person(200),person()])
        self.assertEqual(a['people'][0]['track_id'],b['people'][1]['track_id'])
        self.assertEqual(a['people'][1]['track_id'],b['people'][0]['track_id'])
        self.assertEqual(b['people'][0]['items']['helmet']['state'],'PRESENT')
        self.assertEqual(b['people'][1]['items']['helmet']['state'],'UNKNOWN')

    def test_crossing_overlap_discards_identity_evidence(self):
        self.update(0,complete()+complete(150),[person(),person(150)])
        initial=self.update(0.3,complete()+complete(150),[person(),person(150)])
        out=self.update(0.6,complete(50)+complete(100),[person(50),person(100)])
        self.assertTrue(all(p['identity_ambiguous'] for p in out['people']))
        self.assertTrue(all(p['state']=='UNKNOWN' for p in out['people']))
        self.assertFalse(out['alarm_candidate'])
        self.assertTrue(set(p['track_id'] for p in initial['people']).isdisjoint(p['track_id'] for p in out['people']))

    def test_ambiguous_one_old_to_two_new_not_reused(self):
        initial=self.confirmed_present()['people'][0]['track_id']
        out=self.update(0.6,people=[person(-20),person(20)])
        self.assertTrue(all(p['identity_ambiguous'] for p in out['people']))
        self.assertNotIn(initial,[p['track_id'] for p in out['people']])

    def test_overlapping_person_evidence_unassigned(self):
        out=self.update(0,complete(40),[person(),person(40)])
        self.assertEqual(out['unassigned_equipment'],3)
        self.assertFalse(out['alarm_candidate'])

    def test_multiple_people_never_mix_items_into_three_lights(self):
        equipment=[gear('vest'),gear('shoes',200),gear('helmet',400)]
        self.update(0,equipment,[person(),person(200),person(400)])
        out=self.update(0.3,equipment,[person(),person(200),person(400)])
        self.assertEqual(out['indicators']['mode'],'MULTIPLE_PEOPLE')
        self.assertTrue(all(v is None for v in out['indicators']['lights'].values()))
        self.assertTrue(all(p['state']=='UNKNOWN' for p in out['people']))

    def test_explicit_selected_target_only_shows_its_own_items(self):
        equipment=[gear('vest'),gear('shoes',200),gear('helmet',400)]
        first=self.update(0,equipment,[person(),person(200),person(400)])
        tid=first['people'][0]['track_id']
        out=self.update(0.3,equipment,[person(),person(200),person(400)],selected_track_id=tid)
        self.assertEqual(out['indicators']['lights'],{'vest':True,'shoes':None,'helmet':None})
        self.assertEqual(out['indicators']['track_id'],tid)

    def test_lost_selected_target_does_not_switch_to_another_person(self):
        prior=self.confirmed_present()['people'][0]['track_id']
        out=self.update(0.6,complete(200),[person(200)],selected_track_id=prior)
        self.assertEqual(out['indicators']['mode'],'TARGET_NOT_VISIBLE')
        self.assertTrue(all(v is None for v in out['indicators']['lights'].values()))

    def test_no_cross_person_alarm_confirmation(self):
        # Simultaneous tracks each have only intermittent fresh negatives.
        for i,t in enumerate((0,0.5,1,1.5,2)):
            j=i%2
            out=self.update(t,[gear('helmet',j*200,negative=True)],[person(),person(200)],
                            visibility={0:{'helmet':'OBSERVABLE'},1:{'helmet':'OBSERVABLE'}})
            self.assertFalse(out['alarm_candidate'])

    def test_bad_body_region_never_asserts_negative(self):
        misplaced=D('no_helmet',0.9,(10,170,60,190))
        for t in (0,0.5,1,1.5):
            out=self.update(t,[misplaced],visibility=visibility(helmet='OBSERVABLE'))
        self.assertFalse(out['alarm_candidate'])

    def test_low_confidence_equipment_ignored(self):
        for t in (0,0.5,1,1.5):
            out=self.update(t,[gear('helmet',negative=True,confidence=0.1)],visibility=visibility(helmet='OBSERVABLE'))
        self.assertFalse(out['alarm_candidate'])

    def test_weak_person_filter_keeps_visibility_indices_aligned(self):
        out=self.update(0,[gear('helmet',200,negative=True)],[person(confidence=0.1),person(200)],
                        visibility={0:{'helmet':'NOT_VISIBLE'},1:{'helmet':'OBSERVABLE'}})
        self.assertEqual(out['people'][0]['items']['helmet']['observation'],'ABSENT')

    def test_duplicate_frame_id_even_with_new_timestamp_rejected_and_flushed(self):
        self.confirmed_present()
        with self.assertRaises(ValueError):
            self.tracker.update(self.frame,0.6,[person()],complete())
        self.assertEqual(self.tracker.tracks,{})

    def test_duplicate_timestamp_with_new_frame_rejected_and_flushed(self):
        self.confirmed_present()
        with self.assertRaises(ValueError):
            self.update(0.3,complete())
        self.assertEqual(self.tracker.tracks,{})

    def test_stale_frame_rejected_and_flushed(self):
        self.confirmed_present()
        with self.assertRaises(ValueError):
            self.update(0.6,complete(),received_at=2)
        self.assertEqual(self.tracker.tracks,{})

    def test_future_capture_rejected(self):
        with self.assertRaises(ValueError):
            self.update(1,received_at=0.9)

    def test_nonfinite_timestamps_rejected(self):
        for t in (math.nan,math.inf,-1):
            with self.subTest(t=t),self.assertRaises(ValueError):
                self.update(t)

    def test_faults_flush_every_track(self):
        for fault in ('CAMERA_LOST','MODEL_ERROR','STARTING'):
            with self.subTest(fault=fault):
                self.setUp()
                self.confirmed_present()
                out=self.update(0.6,fault=fault)
                self.assertEqual(out['observation'],fault)
                self.assertFalse(out['alarm_candidate'])
                self.assertEqual(self.tracker.tracks,{})
                recovered=self.update(0.9,complete())
                self.assertEqual(recovered['observation'],'UNKNOWN')

    def test_invalid_detection_fault_not_safe(self):
        self.confirmed_present()
        out=self.update(0.6,[D('helmet',math.nan,(0,0,30,30))])
        self.assertEqual(out['observation'],'MODEL_ERROR')
        self.assertEqual(self.tracker.tracks,{})

    def test_capacity_overflow_fault(self):
        out=self.update(0,people=[person(i*200) for i in range(9)])
        self.assertEqual(out['observation'],'MODEL_ERROR')
        self.assertEqual(self.tracker.tracks,{})

    def test_equipment_capacity_overflow_fault(self):
        out=self.update(0,[gear('helmet')]*65)
        self.assertEqual(out['observation'],'MODEL_ERROR')

    def test_track_handles_bounded_under_many_passers(self):
        for i in range(30):
            out=self.update(i*0.05,people=[person(i*200)])
            self.assertLessEqual(out['retained_track_count'],8)

    def test_bad_visibility_rejected_and_flushed(self):
        self.confirmed_present()
        with self.assertRaises(ValueError):
            self.update(0.6,visibility={0:{'shoes':'VISIBLE'}})
        self.assertEqual(self.tracker.tracks,{})

    def test_orphan_negative_is_unknown_not_empty_or_safe(self):
        out=self.update(0,[gear('helmet',300,negative=True)],people=[])
        self.assertEqual(out['observation'],'UNKNOWN')
        self.assertFalse(out['alarm_candidate'])

    def test_wrong_timestamp_type_invalidates_cache(self):
        self.confirmed_present()
        with self.assertRaises(ValueError):
            self.update(None)
        self.assertEqual(self.tracker.tracks,{})

    def test_invalid_visibility_value_type_invalidates_cache(self):
        self.confirmed_present()
        with self.assertRaises(ValueError):
            self.update(0.6,visibility={0:{'shoes':[]}})
        self.assertEqual(self.tracker.tracks,{})

    def test_bad_target_id_invalidates_cache(self):
        self.confirmed_present()
        with self.assertRaises(ValueError):
            self.update(0.6,selected_track_id=True)
        self.assertEqual(self.tracker.tracks,{})

    def test_outputs_always_disabled(self):
        self.assertFalse(self.confirmed_absent()['hardware_outputs_enabled'])

    def test_invalid_settings(self):
        for change in ({'absent_samples':1},{'match_iou':0},{'max_tracks':100},{'evidence_ttl_seconds':0},
                       {'confidence':math.nan},{'max_gap_seconds':0},{'present_samples':True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(TrackingSettings(),**change)


class WorkshopConfigTests(unittest.TestCase):
    def test_required_policy_is_confirmed_but_deployment_disabled(self):
        c=load_workshop_config()
        self.assertEqual(c['policy']['required'],['vest','shoes','helmet'])
        self.assertTrue(c['policy']['confirmed_by_operator'])
        self.assertFalse(c['target']['deployment_enabled'])
        self.assertFalse(c['actuators']['enabled'])

    def test_model_missing_vest_blocks_production(self):
        c=load_config()
        caps=model_capabilities(c['models']['ppe']['expected_labels'])
        self.assertFalse(caps['label_contract_supported'])
        self.assertEqual(caps['missing_positive'],['vest'])
        self.assertEqual(caps['missing_negative'],['no_vest'])
        self.assertFalse(caps['deployment_ready'])

    def test_even_complete_label_contract_does_not_prove_accuracy(self):
        caps=model_capabilities(['vest','no_vest','shoes','no_shoes','helmet','no_helmet'])
        self.assertTrue(caps['label_contract_supported'])
        self.assertFalse(caps['accuracy_validated'])
        self.assertFalse(caps['deployment_ready'])

    def test_wrong_mapping_or_hardware_enable_rejected(self):
        base=load_workshop_config()
        changes=[('indicator_colors','vest','red'),('target','deployment_enabled',True),('actuators','enabled',True)]
        for section,key,value in changes:
            c=copy.deepcopy(base)
            c[section][key]=value
            with tempfile.TemporaryDirectory() as directory:
                file=Path(directory)/'config.json'
                file.write_text(json.dumps(c),encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_workshop_config(file)

    def test_workshop_walking_fixture_expected_transitions(self):
        source=Path(__file__).parent/'fixtures'/'apd_workshop_replay.jsonl'
        rows=[json.loads(line) for line in source.read_text(encoding='utf-8').splitlines() if line.strip()]
        frames=replay_tracking(rows,load_workshop_config())
        by_id={f['frame_id']:f for f in frames}
        self.assertEqual(len(frames),29)
        self.assertEqual(by_id[2]['people'][0]['items']['shoes']['state'],'UNKNOWN')
        self.assertEqual(by_id[5]['indicators']['lights'],{'vest':True,'shoes':True,'helmet':True})
        self.assertEqual(by_id[6]['people'][0]['items']['shoes']['source'],'CACHED')
        self.assertEqual(by_id[12]['people'][0]['items']['shoes']['state'],'UNKNOWN')
        self.assertFalse(by_id[14]['alarm_candidate'])
        self.assertTrue(by_id[19]['alarm_candidate'])
        self.assertFalse(by_id[21]['alarm_candidate'])
        self.assertEqual(by_id[22]['observation'],'NO_PERSON')
        self.assertNotEqual(by_id[23]['people'][0]['track_id'],by_id[21]['people'][0]['track_id'])
        self.assertTrue(all(p['identity_ambiguous'] for p in by_id[27]['people']))
        self.assertEqual(by_id[28]['observation'],'CAMERA_LOST')
        self.assertEqual(by_id[29]['observation'],'UNKNOWN')
        self.assertTrue(all(not f['hardware_outputs_enabled'] for f in frames))

    def test_json_replay_is_offline_and_cannot_confirm_from_cached_frames(self):
        p={'label':'person','confidence':0.9,'box':[0,0,100,200]}
        rows=[{'frame_id':1,'t':0,'person':[p]}, {'frame_id':2,'t':0.3,'person':[p]}]
        out=replay_tracking(rows,load_workshop_config())
        self.assertTrue(all(not r['hardware_outputs_enabled'] for r in out))
        with self.assertRaises(ValueError):
            replay_tracking([rows[0],dict(rows[1],frame_id=1)],load_workshop_config())
