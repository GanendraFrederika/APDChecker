"""Generate deterministic HOST coordinate vectors; no board or model access.
Independent Python forward corner rotation + actual resize/pad, compared with
C inverse/unletterbox. These are geometry tests, not camera/model calibration.
"""
from pathlib import Path
import random


def forward(box, width, height, rotation):
    points=[]
    for x,y in ((box[0],box[1]),(box[0],box[3]),(box[2],box[1]),(box[2],box[3])):
        if rotation==90: x,y=height-y,x
        elif rotation==180: x,y=width-x,height-y
        elif rotation==270: x,y=y,width-x
        points.append((x,y))
    return [min(x for x,y in points),min(y for x,y in points),
            max(x for x,y in points),max(y for x,y in points)]


def number(value):
    result=format(float(value),'.9g')
    return result+('f' if '.' in result or 'e' in result else '.0f')


def generate_vectors(path):
    rng=random.Random(3336)
    lines=['#include "backend_frame.h"','#include <assert.h>','#include <math.h>',
           '#include <stdio.h>', 'static void check(apd_box actual,apd_box expected) {',
           'assert(fabsf(actual.x1-expected.x1)<0.025f);',
           'assert(fabsf(actual.y1-expected.y1)<0.025f);',
           'assert(fabsf(actual.x2-expected.x2)<0.025f);',
           'assert(fabsf(actual.y2-expected.y2)<0.025f);',
           'assert(actual.confidence==expected.confidence);}',
           'void test_backend_vectors(void) {','apd_frame_transform t; apd_box b,out;']
    count=0
    for rotation in (0,90,180,270):
        for sample in range(256):
            w,h=rng.choice(((2304,1296),(640,480),(1296,2304),(1920,1080)))
            rw,rh=(h,w) if rotation in (90,270) else (w,h)
            scale=min(320/rw,320/rh)
            resized_w,resized_h=max(1,round(rw*scale)),max(1,round(rh*scale))
            # Deliberately asymmetric padding, using actual rounded dimensions.
            px,py=rng.randrange(321-resized_w),rng.randrange(321-resized_h)
            x1=rng.uniform(0,w*0.7); y1=rng.uniform(0,h*0.7)
            original=[x1,y1,rng.uniform(x1+1,w),rng.uniform(y1+1,h)]
            view=forward(original,w,h,rotation)
            model=[view[0]*resized_w/rw+px,view[1]*resized_h/rh+py,
                   view[2]*resized_w/rw+px,view[3]*resized_h/rh+py]
            def box(values):return '(apd_box){'+','.join(number(v) for v in values+[0.9])+'}'
            lines += [f't=(apd_frame_transform){{{w},{h},320,320,{resized_w},{resized_h},{px},{py},{rotation}}};',
                      f'b={box(model)};', 'assert(apd_inverse_box(&t,b,&out)==APD_MAP_BOX);',
                      f'check(out,{box(original)});','assert(apd_unletterbox_box(&t,b,&out)==APD_MAP_BOX);',
                      f'check(out,{box(view)});']
            count+=1
    lines+=['printf("Backend coordinate vectors PASS: '+str(count)+' synthetic boxes; NO CAMERA\\n");','}']
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf8')
    return count
