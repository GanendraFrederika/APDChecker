import unittest
from copy import deepcopy
from apd_runtime.mcu_protocol import hello, heartbeat, stop, data, report_data
from apd_runtime.protocol import decode_frame
from apd_runtime.tracking_offline import replay_tracking, load_workshop_config
from apd_runtime.computer_debug import demo_rows


class MCUProtocolTests(unittest.TestCase):
    def test_hello_stop_heartbeat_are_not_legacy_transport(self):
        for fn, command in ((hello,'HELLO'),(stop,'STOP'),(heartbeat,'H')):
            self.assertEqual(decode_frame(fn(1,'1234ABCD')),(1,[command,'1234ABCD']))
        for bad in ('00000000','xyz','1234abcd',None):
            with self.assertRaises(ValueError): hello(1,bad)

    def test_frame_item_source_order(self):
        frame=data(3,'1234ABCD',17,'VIOLATION',5,'CNU',True)
        self.assertEqual(decode_frame(frame),(3,['DATA','1234ABCD','17','VIOLATION','0000000000000005','CNU','1']))

    def test_invalid_or_inconsistent_payloads(self):
        args=[3,'1234ABCD',17,'VIOLATION',5,'CNU',True]
        for index, bad in ((0,True),(0,65536),(1,'00000000'),(2,True),(2,-1),(2,2**32),
                           (3,'BAD'),(4,True),(4,2**64),(5,'PPPZ'),(5,'ZZZ'),(6,1)):
            copy=args.copy(); copy[index]=bad
            with self.subTest(index=index,bad=bad), self.assertRaises(ValueError): data(*copy)
        for status,target,states,alarm in (('CAMERA_LOST',1,'UUU',False),('NO_PERSON',0,'PPP',False),
                                          ('UNKNOWN',0,'PNU',False),('UNKNOWN',1,'UUU',True),
                                          ('COMPLIANT',1,'PNU',False),('VIOLATION',1,'CDU',True)):
            with self.subTest(status=status), self.assertRaises(ValueError):
                data(1,'1234ABCD',1,status,target,states,alarm)

    def test_reference_demo_always_valid_and_no_global_lamp_or(self):
        reports=replay_tracking(demo_rows(),load_workshop_config())
        for index,report in enumerate(reports):
            raw=report_data(index+1,'1234ABCD',index+1,report)
            _,fields=decode_frame(raw)
            self.assertEqual(fields[0],'DATA')
            if fields[-1]=='1': self.assertIn('N',fields[-2])
        for report in reports:
            corrupted=deepcopy(report); corrupted['hardware_outputs_enabled']=True
            with self.assertRaises(ValueError): report_data(1,'1234ABCD',1,corrupted)

    def test_multi_person_no_selection_never_combines(self):
        report=dict(observation='VIOLATION',hardware_outputs_enabled=False,
                    indicators=dict(track_id=None),people=[])
        self.assertEqual(decode_frame(report_data(1,'1234ABCD',1,report))[1][-3:],['0000000000000000','UUU','0'])


    def test_cached_absence_cannot_trigger_and_other_person_alarm_not_selected(self):
        reports=replay_tracking(demo_rows(),load_workshop_config())
        selected=next(report for report in reports if any(person['alarm_candidate'] for person in report['people']))
        selected=deepcopy(selected)
        person=selected['people'][0]
        for item in person['items'].values():
            if item['state']=='ABSENT': item['source']='CACHED'
        self.assertEqual(decode_frame(report_data(1,'1234ABCD',1,selected))[1][-1],'0')
        person['alarm_candidate']=False
        other=deepcopy(person); other['track_id']=999; other['alarm_candidate']=True
        selected['people'].append(other);selected['alarm_candidate']=True
        self.assertEqual(decode_frame(report_data(1,'1234ABCD',1,selected))[1][-1],'0')

    def test_ambiguous_selected_target_rejected(self):
        report=deepcopy(replay_tracking(demo_rows()[:3],load_workshop_config())[-1])
        report['people'][0]['identity_ambiguous']=True
        with self.assertRaises(ValueError): report_data(1,'1234ABCD',1,report)
