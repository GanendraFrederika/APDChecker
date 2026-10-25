"""Generate independent synthetic INT8 YOLOv5 grid/NMS HOST vectors.
No model, RKNN, camera or serial IO; not real-model INT8 accuracy parity.
"""
from pathlib import Path
import math
import random


def reference(heads, width, height, threshold=0.35, nms=0.45):
    candidates=[]
    for head in heads:
        for a in range(3):
            for y in range(head['h']):
                for x in range(head['w']):
                    raw=head['cells'].get((a,y,x), [-128]*12)
                    p=[max(0,min(1,(v-head['zp'])*head['scale'])) for v in raw]
                    cls=max(range(7),key=lambda k:p[5+k])
                    score=p[4]*p[5+cls]
                    if score<threshold: continue
                    cx=(2*p[0]-.5+x)*head['stride']
                    cy=(2*p[1]-.5+y)*head['stride']
                    bw=(2*p[2])**2*head['anchors'][a][0]
                    bh=(2*p[3])**2*head['anchors'][a][1]
                    b=[max(0,cx-bw/2),max(0,cy-bh/2),min(width,cx+bw/2),min(height,cy+bh/2)]
                    if b[2]>b[0] and b[3]>b[1]: candidates.append((b,score,cls))
    if len(candidates)>256:return None
    candidates.sort(key=lambda c:-c[1]) # stable, deterministic ties
    out=[]
    for b,score,cls in candidates:
        reject=False
        for ob,_,oc in out:
            if cls!=oc:continue
            area=lambda b:(b[2]-b[0])*(b[3]-b[1])
            inter=max(0,min(b[2],ob[2])-max(b[0],ob[0]))*max(0,min(b[3],ob[3])-max(b[1],ob[1]))
            if inter/(area(b)+area(ob)-inter)>nms:reject=True;break
        if not reject:out.append((b,score,cls))
    return None if len(out)>72 else out


def number(value):
    s=format(value,'.9g')
    return s+'f' if '.' in s or 'e' in s else s+'.0f'


def generate_test(path):
    rng=random.Random(11033336)
    lines=['#include "grid_decoder.h"','#include <assert.h>','#include <string.h>',
           '#include <math.h>','#include <stdio.h>',
           'static int8_t data[3][24000]; static apd_grid_workspace w;',
           'void test_grid_vectors(void) {', 'apd_grid_input in; apd_raw_detection out[72]; size_t count;']
    for vector in range(256):
        size=rng.choice((32,64,96));scale=rng.choice((1/255,1/128));heads=[]
        lines+=['memset(&in,0,sizeof(in));',f'in.contract=1; in.input_width={size}; in.input_height={size};',
                'in.score_threshold=0.35f; in.nms_iou=0.45f;']
        for i,stride in enumerate((8,16,32)):
            gw=size//stride;row=gw+rng.randint(0,4);channel=row*gw+rng.randint(0,4)
            anchors=[(rng.randint(3,72),rng.randint(3,72)) for _ in range(3)]
            head=dict(w=gw,h=gw,stride=stride,scale=scale,zp=-128,anchors=anchors,cells={})
            for _ in range(rng.randrange(0,18)):
                key=(rng.randrange(3),rng.randrange(gw),rng.randrange(gw))
                maxq=127 if scale==1/255 else 0
                raw=[rng.randint(-128,maxq) for _ in range(12)]
                head['cells'][key]=raw
            heads.append(head)
            lines += [f'memset(data[{i}],127,sizeof(data[{i}]));',
                      f'in.heads[{i}]=(apd_grid_head){{data[{i}],sizeof(data[{i}]),{row},{channel},{gw},{gw},{stride},-128,{number(scale)},{{'+','.join('{'+f'{a}.0f,{b}.0f'+'}' for a,b in anchors)+'}};',
                      f'for(size_t c=0;c<36;++c) for(size_t y=0;y<{gw};++y) for(size_t x=0;x<{gw};++x) data[{i}][c*{channel}+y*{row}+x]=-128;']
            for (a,y,x),raw in head['cells'].items():
                for c,v in enumerate(raw): lines.append(f'data[{i}][{(a*12+c)*channel+y*row+x}]={v};')
        expected=reference(heads,size,size)
        if expected is None:
            lines+=['assert(!apd_grid_decode(&in,&w,out,72,&count)); assert(count==0);']
        else:
            lines += ['assert(apd_grid_decode(&in,&w,out,72,&count));',f'assert(count=={len(expected)});']
            for j,(b,score,cls) in enumerate(expected):
                lines.append(f'assert(out[{j}].class_id=={cls});')
                for field,value in zip(('x1','y1','x2','y2','confidence'),b+[score]):
                    lines.append(f'assert(fabsf(out[{j}].box.{field}-{number(value)})<0.002f);')
                lines.append(f'for(size_t k=0;k<3;++k) assert(out[{j}].visibility[k]==WS_VIS_UNKNOWN);')
    lines+=['puts("Grid C/Python differential PASS: 256 synthetic tensors, NOT model accuracy");','}']
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf8')
    return 256
