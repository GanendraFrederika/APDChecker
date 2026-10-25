"""Supervised camera resource test; no PPE inference/UART/Arduino.
Uses installed bounded local guard. Captures numeric metrics and optional RTSP
frame delivery on HOST, never saves images. Refuses takeover of forward port.
"""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from audit_luckfox_thermal import adb_output,ROOT,SAMPLE
from control_luckfox_preview import control
sys.path.insert(0,str(ROOT/'python'))
from apd_runtime.thermal_audit import blocks,temperature,cpu_counters,cpu_usage,summarize

WORKER=r"""
import cv2,time,json,sys
seconds=int(sys.argv[1]); deadline=time.monotonic()+seconds
c=cv2.VideoCapture('rtsp://127.0.0.1:18554/live/0',cv2.CAP_FFMPEG,
 [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,5000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,3000])
if not c.isOpened(): raise SystemExit('RTSP open failed')
print(json.dumps({'event':'opened','inference':False,'saved_images':False}),flush=True)
count=0;window=0;start=time.monotonic();last=start;shape=None
while time.monotonic()<deadline:
 ok,f=c.read()
 if not ok: print(json.dumps({'event':'read_failed'}),flush=True); c.release();raise SystemExit(2)
 count+=1;window+=1;shape=f.shape;now=time.monotonic()
 if now-last>=10:
  print(json.dumps({'event':'window','frames':window,'seconds':now-last,
   'delivery_fps':window/(now-last),'total_frames':count,'shape':shape}),flush=True)
  window=0;last=now
c.release()
print(json.dumps({'event':'complete','frames':count,'seconds':time.monotonic()-start,
 'shape':shape,'sensor_fps_claim':False}),flush=True)
"""

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial',required=True)
    p.add_argument('--duration',type=int,default=300)
    p.add_argument('--cutoff-c',type=int,default=60)
    p.add_argument('--operator-supervised',action='store_true',required=True)
    p.add_argument('--view-stream',action='store_true')
    args=p.parse_args()
    if not 30<=args.duration<=300 or not 40<=args.cutoff_c<=78:p.error('duration 30..300 / cutoff 40..78 C')
    adb=ROOT/'platform-tools/adb.exe'
    out=ROOT/'docs/luckfox/debug/supervised-camera'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    rows=[];previous=None;previous_uptime=None;errors=[];worker=None;forward=False;started=False
    stream_stdout=stream_stderr=None; stop_confirmed=False
    try:
        status=control(adb,args.serial,'status');(out/'before.txt').write_text(status,encoding='utf8')
        if 'CAMERA_IDLE' not in status:raise RuntimeError('camera not idle; refusing takeover')
        if args.view_stream:
            existing=subprocess.run([str(adb),'forward','--list'],capture_output=True,text=True,timeout=10)
            existing.check_returncode()
            if 'tcp:18554' in existing.stdout:raise RuntimeError('forward port in use; refusing takeover')
            subprocess.run([str(adb),'-s',args.serial,'forward','tcp:18554','tcp:554'],check=True,timeout=10);forward=True
        # A partial start / lost ADB response still requires an explicit stop.
        started=True
        result=control(adb,args.serial,'start',duration=args.duration,cutoff_c=args.cutoff_c)
        print(result,flush=True);(out/'start.txt').write_text(result,encoding='utf8')
        begin=time.monotonic();deadline=begin+args.duration+20
        while time.monotonic()<deadline:
            data=blocks(adb_output(adb,args.serial,SAMPLE).decode(errors='replace'))
            temp=temperature(data['thermal']);up=float(data['uptime'].split()[0])
            if not math.isfinite(up) or (previous_uptime is not None and up<=previous_uptime):raise RuntimeError('board reboot/uptime rollback')
            counters=cpu_counters(data['stat'])
            row={'host_utc':datetime.now(timezone.utc).isoformat(),'uptime_seconds':up,
                 'temperature_c':temp,'cpu':cpu_usage(previous,counters) if previous else None,
                 'memory':data['memory'],'rkipc_pid':data['rkipc'],'pipeline':data['camera_pipeline']}
            rows.append(row);previous=counters;previous_uptime=up
            with (out/'samples.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row)+'\n')
            print(json.dumps({k:v for k,v in row.items() if k!='pipeline'}),flush=True)
            if temp>=args.cutoff_c:raise RuntimeError('requested host temperature cutoff reached')
            if worker and worker.poll() is not None and worker.returncode:raise RuntimeError('RTSP worker failed')
            elapsed=time.monotonic()-begin
            if args.view_stream and worker is None and elapsed>=8:
                stream_stdout=(out/'stream.jsonl').open('wb');stream_stderr=(out/'stream.stderr.txt').open('wb')
                worker=subprocess.Popen([sys.executable,'-c',WORKER,str(max(10,args.duration-25))],stdout=stream_stdout,stderr=stream_stderr)
            if not row['rkipc_pid']:
                if elapsed<args.duration-12:raise RuntimeError('camera exited early')
                break
            time.sleep(10)
        if worker:
            worker.wait(timeout=10)
            if worker.returncode:errors.append('RTSP worker failed')
        logs=adb_output(adb,args.serial,"tail -160 /tmp/apd-preview.log\nprintf '@@ dmesg\\n'; dmesg | tail -100\n")
        (out/'logs.txt').write_bytes(logs)
        if b'APD_GUARD_STOP=TIME_LIMIT' not in logs:errors.append('automatic TIME_LIMIT not confirmed')
    except Exception as exc:
        errors.append(str(exc));print('TEST STOPPING:',exc,flush=True)
    finally:
        if worker and worker.poll() is None:worker.kill();worker.wait(timeout=10)
        for f in (stream_stdout,stream_stderr):
            if f:f.close()
        if started:
            try:
                stopped=control(adb,args.serial,'stop');status=control(adb,args.serial,'status')
                (out/'stop.txt').write_text(stopped+status,encoding='utf8');print(stopped+status,flush=True)
                stop_confirmed='CAMERA_IDLE' in status
            except Exception as exc:errors.append('STOP UNCONFIRMED: '+str(exc))
        if forward:
            try:
                removed=subprocess.run([str(adb),'-s',args.serial,'forward','--remove','tcp:18554'],capture_output=True,timeout=10)
                if removed.returncode:errors.append('forward cleanup failed')
            except Exception as exc:errors.append('forward cleanup '+str(exc))
        report={'serial':args.serial,'requested_seconds':args.duration,'requested_cutoff_c':args.cutoff_c,
                'cutoff_not_chip_rating':True,'operator_supervised':True,'cooling':'operator reports nearby fan; no installed heatsink yet',
                'summary':summarize(rows),'errors':errors,'camera_stop_confirmed':stop_confirmed,
                'ppe_inference':False,'npu_load_test':False,'image_saved':False,'production_ready':False}
        (out/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf8');print('EVIDENCE',out,flush=True)
    return 2 if errors else 0
if __name__=='__main__':raise SystemExit(main())
