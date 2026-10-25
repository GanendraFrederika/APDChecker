"""Supervised vendor RockIVA NPU smoke test. NOT APD and NOT a deployment.
Uses only shipped rkipc/library/models; temporary /tmp config and guard, no
/userdata config/boot/runtime/model replacement, image saving or MCU access.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from audit_luckfox_thermal import ROOT, SAMPLE, adb_output
from apd_runtime.thermal_audit import blocks, temperature, cpu_counters, cpu_usage, summarize

SERIAL = '2be53eb6debe9106'
SESSION = '/tmp/apd-vendor-npu-session.sh'
CTL = '/tmp/apd-vendor-npuctl.sh'
CONFIG = '/tmp/apd-vendor-npu.ini'
LOG = '/tmp/apd-vendor-npu.log'
EXTRA = r"""
printf '@@ npu_interrupts\n'; grep 'ff660000.npu' /proc/interrupts
printf '@@ npu_threads\n'
p=$(pidof rkipc); if [ -n "$p" ]; then for f in /proc/$p/task/*/comm; do cat "$f"; done; fi
printf '@@ npu_logs\n'; tail -100 /tmp/apd-vendor-npu.log
"""

def change_key(text, section, key, expected, value):
    current = None
    found = 0
    lines = []
    for line in text.splitlines(keepends=True):
        m = re.fullmatch(r'\s*\[([^]]+)\]\s*', line.strip())
        if m: current = m.group(1)
        m = re.match(r'^(\s*' + re.escape(key) + r'\s*=\s*)([^\r\n]+)(\r?\n)?$', line)
        if current == section and m:
            if m.group(2).strip() != expected: raise ValueError('unexpected ' + section + ':' + key)
            found += 1
            line = m.group(1) + value + (m.group(3) or '')
        lines.append(line)
    if found != 1: raise ValueError('missing/duplicate ' + section + ':' + key)
    return ''.join(lines)

def candidate(text):
    # Keep 10 FPS sensor + encoder and shipped small PFP model; request 3 FPS NPU.
    text = change_key(text, 'video.source', 'enable_npu', '0', '1')
    # Verify no unsupported profile, recording, secondary stream or audio takeover.
    for section, key, value in [('video.source','npu_fps','3'),
        ('video.source','enable_ivs','0'), ('video.source','enable_jpeg','0'),
        ('video.source','enable_venc_1','0'), ('video.source','enable_venc_2','0'),
        ('audio.0','enable','0'), ('storage.0','enable','0'),
        ('storage.1','enable','0'), ('storage.2','enable','0'),
        ('event.regional_invasion','rockiva_model_type','small')]:
        text = change_key(text, section, key, value, value)
    return text

def irq_count(text):
    m = re.fullmatch(r'\s*\d+:\s*(\d+)\s+[A-Za-z][^\n]*\bff660000\.npu\s*', text.strip())
    if not m: raise ValueError('missing/invalid single CPU NPU interrupt counter')
    return int(m.group(1))

def control(adb, serial, command):
    if command not in ('stop','status'):
        m = re.fullmatch(r'start ([0-9]{2,3}) ([0-9]{2})', command)
        if not m or not 30 <= int(m.group(1)) <= 300 or not 40 <= int(m.group(2)) <= 78:
            raise ValueError('invalid bounded vendor command')
    output = adb_output(adb, serial, 'sh '+CTL+' '+command+'\nrc=$?; echo APD_VENDOR_EXIT=$rc\n').decode(errors='replace')
    if 'APD_VENDOR_EXIT=0' not in output: raise RuntimeError(output)
    return output

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True, choices=[SERIAL])
    p.add_argument('--duration',type=int,default=60)
    p.add_argument('--cutoff-c',type=int,default=60)
    p.add_argument('--operator-supervised',action='store_true',required=True)
    args=p.parse_args()
    if not 30<=args.duration<=300 or not 40<=args.cutoff_c<=78:p.error('duration 30..300, cutoff 40..78')
    adb=ROOT/'platform-tools/adb.exe'
    out=ROOT/'docs/luckfox/debug/vendor-npu'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    rows=[];errors=[];started=False;stop_ok=False;previous=None;up_before=None
    try:
        pre=adb_output(adb,args.serial,"cat /proc/device-tree/model; printf '\\n@@ camera\\n'; pidof rkipc || true; printf '@@ lock\\n'; ls -d /tmp/apd-preview-session /tmp/apd-vendor-npu-state 2>/dev/null || true; printf '@@ interrupts\\n'; grep ff660000.npu /proc/interrupts\n").decode(errors='replace')
        (out/'before.txt').write_text(pre,encoding='utf8')
        if not pre.startswith('Luckfox Pico Mini B\x00') or blocks(pre).get('camera','').strip() or blocks(pre).get('lock','').strip():raise RuntimeError('board not idle/no takeover')
        baseline=irq_count(blocks(pre)['interrupts'])
        subprocess.run([str(adb),'-s',args.serial,'pull','/userdata/rkipc.ini',str(out/'rkipc.ini.original')],check=True,capture_output=True,timeout=20)
        original=(out/'rkipc.ini.original').read_bytes()
        (out/'candidate.ini').write_text(candidate(original.decode('utf8')),encoding='utf8',newline='')
        session=(ROOT/'edge/luckfox/apd-preview-session.sh').read_text().replace('/tmp/apd-preview-session','/tmp/apd-vendor-npu-state').replace('/tmp/apd-preview.log',LOG).replace('/userdata/apd-preview-session.sh',SESSION).replace('/userdata/rkipc.ini',CONFIG).replace('-l 0','-l 3')
        ctl=(ROOT/'edge/luckfox/apd-previewctl.sh').read_text().replace('/tmp/apd-preview-session','/tmp/apd-vendor-npu-state').replace('/tmp/apd-preview.log',LOG).replace('/userdata/apd-preview-session.sh',SESSION).replace('/tmp/apd-preview-guard.log','/tmp/apd-vendor-npu-guard.log').replace('PREVIEW_STARTED','VENDOR_NPU_PROCESS_STARTED_NOT_PPE')
        for name,text in [('session.sh',session),('ctl.sh',ctl)]: (out/name).write_text(text,encoding='utf8',newline='')
        for local,remote in [('candidate.ini',CONFIG),('session.sh',SESSION),('ctl.sh',CTL)]:
            subprocess.run([str(adb),'-s',args.serial,'push',str(out/local),remote],check=True,capture_output=True,timeout=20)
            expected=hashlib.sha256((out/local).read_bytes()).hexdigest()
            verify=adb_output(adb,args.serial,'sha256sum '+remote+'\n').decode()
            if not verify.startswith(expected):raise RuntimeError('temporary upload hash mismatch')
        syntax=adb_output(adb,args.serial,'sh -n '+SESSION+' && sh -n '+CTL+' && echo VENDOR_SYNTAX_OK\n')
        if b'VENDOR_SYNTAX_OK' not in syntax:raise RuntimeError('shell syntax invalid')
        # Mark ownership attempt BEFORE start: even a partial startup gets explicit stop.
        started=True
        start=control(adb,args.serial,f'start {args.duration} {args.cutoff_c}')
        (out/'start.txt').write_text(start);print(start,flush=True)
        begin=time.monotonic()
        while time.monotonic()-begin<args.duration+20:
            data=blocks(adb_output(adb,args.serial,SAMPLE+EXTRA).decode(errors='replace'))
            temp=temperature(data['thermal']);up=float(data['uptime'].split()[0]);counter=cpu_counters(data['stat'])
            if up_before is not None and up<=up_before:raise RuntimeError('uptime rollback')
            irq=irq_count(data['npu_interrupts']);available=re.search(r'MemAvailable:\s+(\d+)',data['memory'])
            if not available:raise RuntimeError('memory unavailable')
            row={'host_utc':datetime.now(timezone.utc).isoformat(),'uptime_seconds':up,'temperature_c':temp,
                'cpu':cpu_usage(previous,counter) if previous else None,'memory':data['memory'],
                'npu_interrupt_count':irq,'npu_interrupt_delta':irq-baseline,
                'threads':data['npu_threads'],'rkipc_pid':data['rkipc'],'pipeline':data['camera_pipeline']}
            rows.append(row);previous=counter;up_before=up
            with (out/'samples.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row)+'\n')
            with (out/'logs-snapshots.txt').open('a',encoding='utf8') as f:f.write('\n'+row['host_utc']+'\n'+data['npu_logs'])
            print(json.dumps({k:v for k,v in row.items() if k not in ('pipeline','threads','memory')}),flush=True)
            if temp>=args.cutoff_c:raise RuntimeError('requested thermal cutoff')
            if int(available.group(1))<2048:raise RuntimeError('low MemAvailable')
            if irq<baseline:raise RuntimeError('interrupt counter rollback')
            if not data['rkipc']:
                if time.monotonic()-begin<args.duration-8:raise RuntimeError('vendor camera/NPU exited early')
                break
            time.sleep(5)
        logs=adb_output(adb,args.serial,'cat '+LOG+"\nprintf '@@ dmesg\\n'; dmesg | tail -80\n")
        (out/'logs.txt').write_bytes(logs)
        if b'APD_GUARD_STOP=TIME_LIMIT' not in logs:errors.append('TIME_LIMIT not confirmed')
        if b'ROCKIVA_BA_Init success' not in logs:errors.append('vendor init success not confirmed')
        active=[r['npu_interrupt_count'] for r in rows if r['rkipc_pid']]
        if len(active)<3 or sum(b>a for a,b in zip(active,active[1:]))<2:
            errors.append('sustained NPU interrupt activity not confirmed')
    except Exception as exc:
        errors.append(str(exc));print('VENDOR TEST STOPPING:',exc,flush=True)
    finally:
        if started:
            try:
                stop=control(adb,args.serial,'stop');status=control(adb,args.serial,'status')
                (out/'stop.txt').write_text(stop+status);print(stop+status,flush=True)
                stop_ok='CAMERA_IDLE' in status
                if not stop_ok:errors.append('camera idle not confirmed')
            except Exception as exc:errors.append('STOP UNCONFIRMED '+str(exc))
        try:
            subprocess.run([str(adb),'-s',args.serial,'pull','/userdata/rkipc.ini',str(out/'rkipc.ini.after')],check=True,capture_output=True,timeout=20)
            unchanged=(out/'rkipc.ini.original').read_bytes()==(out/'rkipc.ini.after').read_bytes()
            if not unchanged:errors.append('userdata config changed externally during test')
        except Exception as exc:unchanged=False;errors.append('config verification '+str(exc))
        report={'serial':args.serial,'requested_seconds':args.duration,'requested_cutoff_c':args.cutoff_c,
            'cutoff_not_chip_rating':True,'summary':summarize(rows),'errors':errors,
            'camera_stop_confirmed':stop_ok,'persistent_config_unchanged':unchanged,
            'vendor_npu_interrupt_activity_observed':any(r['npu_interrupt_delta']>0 for r in rows),
            'measured_inference_fps':None,'requested_npu_fps':3,'ppe_inference':False,
            'production_ready':False,'images_saved':False,'cooling':'operator-reported nearby fan, no installed heatsink yet'}
        (out/'summary.json').write_text(json.dumps(report,indent=2));print('EVIDENCE',out,flush=True)
    return 2 if errors else 0

if __name__=='__main__':raise SystemExit(main())
