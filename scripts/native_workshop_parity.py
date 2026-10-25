"""Generate HOST C asserts from independent existing Python workshop replay.
Also checks APD3 C/Python bytes and actual C receiver acceptance or rejection.
Only synthetic input/policy parity. Never connects to a board or loads weights.
"""
import copy
import json
import random
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'python'))
from apd_runtime.computer_debug import demo_rows
from apd_runtime.tracking_offline import replay_tracking, load_workshop_config
from apd_runtime.mcu_protocol import report_data

ITEMS = ('vest','shoes','helmet')
STATE = {x:'WS_'+x for x in ('UNKNOWN','PRESENT','ABSENT','CONFLICT')}
VIS = {'UNKNOWN':'WS_VIS_UNKNOWN','OBSERVABLE':'WS_OBSERVABLE','NOT_VISIBLE':'WS_NOT_VISIBLE'}

def scenarios():
    walking = [json.loads(line) for line in (ROOT/'tests/fixtures/apd_workshop_replay.jsonl').read_text().splitlines()]
    # Each sequence gets an independent tracker. Both are already regression fixtures.
    motion = [json.loads(line) for line in (ROOT/'tests/fixtures/apd_camera_motion_replay.jsonl').read_text().splitlines()]
    rows = [walking, demo_rows(), motion]
    # Multi-person and conflict/low-confidence alignment additional synthetic replays.
    person = dict(label='person',confidence=0.9,box=[0,0,100,200])
    other = dict(label='person',confidence=0.9,box=[150,0,250,200])
    items = [dict(label=k,confidence=0.9,box=b) for k,b in zip(ITEMS,([20,60,80,130],[10,170,90,195],[10,5,60,35]))]
    two=[]
    for i in range(8):
        equipment=copy.deepcopy(items)
        equipment += [dict(label=k,confidence=0.9,box=[b[0]+150,b[1],b[2]+150,b[3]]) for k,b in zip(ITEMS,([20,60,80,130],[10,170,90,195],[10,5,60,35]))]
        equipment[3]['label']='no_vest'
        two.append(dict(frame_id=i+1,t=i*0.3,person=[person,other],ppe=equipment,
                        visibility={'1':{'vest':'OBSERVABLE'}},selected_track_id=1))
    rows.append(two)
    conflict=copy.deepcopy(demo_rows()[:3])
    conflict.append(dict(frame_id=4,t=0.9,person=[person],ppe=items+[dict(label='no_helmet',confidence=0.9,box=[10,5,60,35])]))
    rows.append(conflict)
    # Deterministic differential stress: crossings, missing people, confidence,
    # hidden body parts, conflicts, opposing PPE, selector and inference gaps.
    rng=random.Random(1103)
    for sequence in range(8):
        random_rows=[]; now=0.0
        for frame in range(64):
            now+=rng.choice((0.25,0.5,0.5,1.0))
            people=[]; equipment=[]; visible={}
            for person_index in range(rng.randrange(4)):
                x=rng.choice((0,20,150,170,300))
                people.append(dict(label='person',confidence=rng.choice((0.2,0.9)),box=[x,0,x+100,200]))
                visible[str(person_index)]={kind:rng.choice(tuple(VIS)) for kind in ITEMS}
                for kind,box in zip(ITEMS,([20,60,80,130],[10,170,90,195],[10,5,60,35])):
                    raw=rng.choice(('missing','positive','negative','conflict'))
                    shifted=[box[0]+x,box[1],box[2]+x,box[3]]
                    if raw in ('positive','conflict'):
                        equipment.append(dict(label=kind,confidence=rng.choice((0.2,0.9)),box=shifted))
                    if raw in ('negative','conflict'):
                        equipment.append(dict(label='no_'+kind,confidence=0.9,box=shifted))
            random_rows.append(dict(frame_id=frame+1,t=now,person=people,ppe=equipment,
                                    visibility=visible,selected_track_id=rng.choice((None,1,5,999))))
        rows.append(random_rows)
    return rows

def literal(value):
    return format(float(value),'.9g') + ('f' if '.' in format(float(value),'.9g') else '.0f')

def generate_test(output):
    config=load_workshop_config()
    lines=['#include "workshop_tracker.h"','#include "mcu_frame.h"','#include "receiver_core.h"','#include <assert.h>','#include <stdio.h>','#include <string.h>',
           'int main(void) {','ws_tracker tracker; ws_frame f; ws_report r;',
           'char wire[APD_MCU_WIRE_BYTES];',
           'ws_settings settings=ws_defaults();','assert(!ws_outputs_enabled());']
    count=0
    for seq in scenarios():
        expected=replay_tracking(seq,config)
        lines.append('assert(ws_init(&tracker,settings));')
        for row,result in zip(seq,expected):
            lines += ['memset(&f,0,sizeof(f));',f'f.frame_id={row["frame_id"]};',f'f.captured_ms={round(row["t"]*1000)};',
                      f'f.received_ms={round(row.get("received_at",row["t"])*1000)};',f'f.people_count={len(row.get("person",[]))};',
                      f'f.equipment_count={len(row.get("ppe",[]))};']
            lines += [f'f.camera_view_epoch={row.get("camera_view_epoch",0)};',
                      f'f.camera_view_unstable={"true" if row.get("camera_view_unstable",False) else "false"};']
            if row.get('fault'): lines.append('f.fault=APD_'+row['fault']+';')
            if row.get('selected_track_id'):lines.append(f'f.selected_track_id={row["selected_track_id"]};')
            for i,person in enumerate(row.get('person',[])):
                values=','.join(literal(v) for v in person['box']+[person['confidence']])
                lines.append(f'f.people[{i}]=(apd_box){{{values}}};')
            for i,item in enumerate(row.get('ppe',[])):
                values=','.join(literal(v) for v in item['box']+[item['confidence']])
                kind=item['label'].removeprefix('no_').upper()
                negative='true' if item['label'].startswith('no_') else 'false'
                lines.append(f'f.equipment[{i}]=(apd_equipment){{{{{values}}},APD_{kind},{negative}}};')
            for i,vis in row.get('visibility',{}).items():
                for kind,value in vis.items():lines.append(f'f.visibility[{i}][WS_{kind.upper()}]={VIS[value]};')
            lines += ['assert(ws_update(&tracker,&f,&r));',f'assert(r.observation==APD_{result["observation"]});',
                      f'assert(r.people_count=={len(result["people"])});',
                      f'assert(r.alarm_candidate=={"true" if result["alarm_candidate"] else "false"});']
            if 'retained_track_count' in result:lines.append(f'assert(r.retained_tracks=={result["retained_track_count"]});')
            if 'unassigned_equipment' in result:lines.append(f'assert(r.unassigned_equipment=={result["unassigned_equipment"]});')
            for i,person in enumerate(result['people']):
                lines += [f'assert(r.people[{i}].id=={person["track_id"]});',
                          f'assert(r.people[{i}].observation==APD_{person["state"]});',
                          f'assert(r.people[{i}].identity_ambiguous=={"true" if person["identity_ambiguous"] else "false"});']
                for k,kind in enumerate(ITEMS):
                    item=person['items'][kind]
                    lines += [f'assert(r.people[{i}].items[{k}].state=={STATE[item["state"]]});',
                              f'assert(r.people[{i}].items[{k}].observation=={STATE[item["observation"]]});',
                              f'assert(r.people[{i}].items[{k}].source==WS_{item["source"]});',
                              f'assert(r.people[{i}].items[{k}].has_observed=={"true" if item["observed_at"] is not None else "false"});']
                    if item['observed_at'] is not None:
                        lines.append(f'assert(r.people[{i}].items[{k}].observed_ms=={round(item["observed_at"]*1000)});')
            lines.append(f'assert(r.indicator_track_id=={result["indicators"]["track_id"] or 0});')
            for k,kind in enumerate(ITEMS):
                light=result['indicators']['lights'][kind]
                state='WS_UNKNOWN' if light is None else 'WS_PRESENT' if light else 'WS_ABSENT'
                lines.append(f'assert(r.indicators[{k}]=={state});')
            try:
                wire=report_data(2,'1234ABCD',row['frame_id'],result).decode('ascii')
            except ValueError:
                target=result['indicators']['track_id']
                assert any(p['track_id']==target and p['identity_ambiguous'] for p in result['people'])
                lines += [f'assert(!apd_mcu_encode_report(2,"1234ABCD",{row["frame_id"]},&r,wire,sizeof(wire)));',
                          'assert(wire[0]==0);']
            else:
                alarm='true' if wire.split('*')[0].endswith(',1') else 'false'
                lines += [f'assert(apd_mcu_encode_report(2,"1234ABCD",{row["frame_id"]},&r,wire,sizeof(wire)));',
                          f'assert(strcmp(wire,{json.dumps(wire)})==0);',
                          '{ mcu_receiver receiver; char ack[MCU_LINE_BYTES],hello[APD_MCU_WIRE_BYTES];',
                          'mcu_init(&receiver); assert(apd_mcu_encode_hello(1,"1234ABCD",hello,sizeof(hello)));',
                          'for(size_t byte=0;byte<strlen(hello);++byte) mcu_feed(&receiver,hello[byte],0,ack,sizeof(ack));',
                          'assert(receiver.handshake); bool accepted=false;',
                          'for(size_t byte=0;byte<strlen(wire);++byte) if(mcu_feed(&receiver,wire[byte],0,ack,sizeof(ack))) accepted=true;',
                          'assert(accepted);', f'assert(receiver.alarm_on=={alarm});','}']
            count+=1
    lines += [
        '/* Duplicate/stale/future frames invalidate all evidence. */',
        'assert(!ws_update(&tracker,&f,&r)); assert(r.observation==APD_MODEL_ERROR); assert(tracker.count==0);',
        'assert(ws_init(&tracker,settings)); memset(&f,0,sizeof(f)); f.frame_id=1; f.captured_ms=1000; f.received_ms=2000;',
        'assert(!ws_update(&tracker,&f,&r)); assert(r.observation==APD_MODEL_ERROR);',
        'assert(ws_init(&tracker,settings)); f.captured_ms=2000; f.received_ms=1000;',
        'assert(!ws_update(&tracker,&f,&r));',
        'assert(ws_init(&tracker,settings)); memset(&f,0,sizeof(f)); f.people_count=APD_MAX_PEOPLE+1;',
        'assert(!ws_update(&tracker,&f,&r));',
        'assert(ws_init(&tracker,settings)); memset(&f,0,sizeof(f)); f.frame_id=1;',
        'assert(ws_update(&tracker,&f,&r)); ws_tick(&tracker,750,&r); assert(r.observation==APD_CAMERA_LOST);',
        'assert(tracker.count==0); assert(!r.alarm_candidate); assert(!ws_outputs_enabled());',
        '/* Clock wrapping remains monotonic by unsigned differences. */',
        'assert(ws_init(&tracker,settings)); memset(&f,0,sizeof(f)); f.frame_id=1; f.captured_ms=UINT32_MAX-100; f.received_ms=f.captured_ms;',
        'assert(ws_update(&tracker,&f,&r)); f.frame_id=2; f.captured_ms=100; f.received_ms=100;',
        'assert(ws_update(&tracker,&f,&r));',
        '/* Encoder misuse must return no sendable buffer. */',
        'memset(&r,0,sizeof(r)); r.observation=APD_COMPLIANT;',
        'assert(!apd_mcu_encode_report(0,"1234ABCD",1,&r,wire,sizeof(wire))); assert(wire[0]==0);',
        'assert(!apd_mcu_encode_report(1,"00000000",1,&r,wire,sizeof(wire))); assert(wire[0]==0);',
        'assert(!apd_mcu_encode_report(1,"1234abcd",1,&r,wire,sizeof(wire))); assert(wire[0]==0);',
        'assert(!apd_mcu_encode_report(1,"1234ABCD",1,NULL,wire,sizeof(wire))); assert(wire[0]==0);',
        'assert(!apd_mcu_encode_report(1,"1234ABCD",1,&r,NULL,0));',
        'assert(!apd_mcu_encode_report(1,"1234ABCD",1,&r,wire,10)); assert(wire[0]==0);',
        'r.indicator_track_id=1; r.people_count=1; r.people[0].id=1;',
        'r.people[0].items[0].state=WS_PRESENT; r.people[0].items[0].source=WS_NONE;',
        'assert(!apd_mcu_encode_report(1,"1234ABCD",1,&r,wire,sizeof(wire))); assert(wire[0]==0);',
        'printf("Workshop C policy parity passed; tracker size=%zu bytes; NO HARDWARE\\n",sizeof(tracker));',
        'return 0; }']
    Path(output).write_text('\n'.join(lines)+'\n',encoding='utf8')
    return count

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print('Generated synthetic frames:',generate_test(args.output))
