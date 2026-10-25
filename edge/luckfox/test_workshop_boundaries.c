/* HOST-only invalid input/time/capacity boundaries. No hardware IO. */
#include "workshop_tracker.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static ws_frame person_frame(uint64_t id,uint32_t now) {
    ws_frame f; memset(&f,0,sizeof(f)); f.frame_id=id; f.captured_ms=now; f.received_ms=now;
    f.people_count=1; f.people[0]=(apd_box){0,0,100,200,0.9f};
    f.equipment_count=1; f.equipment[0]=(apd_equipment){{10,5,60,35,0.9f},APD_HELMET,false};
    return f;
}
static void rejected(ws_tracker *t,ws_frame *f,ws_report *r) {
    assert(!ws_update(t,f,r)); assert(t->count==0 && r->observation==APD_MODEL_ERROR);
    assert(!r->people_count && !r->alarm_candidate && !r->indicator_track_id);
    for(size_t k=0;k<WS_ITEMS;++k) assert(r->indicators[k]==WS_UNKNOWN);
}
int main(void) {
    ws_tracker t; ws_report r; ws_settings s=ws_defaults(),bad; ws_frame f;
    assert(!ws_init(NULL,s));
    bad=s; bad.confidence=NAN; assert(!ws_init(&t,bad));
    bad=s; bad.match_iou=0; assert(!ws_init(&t,bad));
    bad=s; bad.overlap_fraction=INFINITY; assert(!ws_init(&t,bad));
    bad=s; bad.present_ms=0; assert(!ws_init(&t,bad));
    bad=s; bad.absent_ms=UINT32_MAX; assert(!ws_init(&t,bad));
    bad=s; bad.present_samples=1; assert(!ws_init(&t,bad));
    bad=s; bad.absent_samples=1; assert(!ws_init(&t,bad));
    assert(ws_init(&t,s)); memset(&r,0,sizeof(r)); ws_tick(&t,0,&r);
    assert(r.observation==APD_STARTING);
    f=person_frame(1,0);
    assert(!ws_update(NULL,&f,&r)); assert(!ws_update(&t,NULL,&r)); assert(!ws_update(&t,&f,NULL));
    assert(ws_update(&t,&f,&r)); f=person_frame(2,300); assert(ws_update(&t,&f,&r));
    assert(r.people[0].items[WS_HELMET].state==WS_PRESENT);
    ws_tick(&t,1049,&r); assert(r.people[0].items[WS_HELMET].state==WS_PRESENT);
    ws_tick(&t,1050,&r); assert(r.observation==APD_CAMERA_LOST && t.count==0 && !r.indicator_track_id);
    f=person_frame(3,1100); assert(ws_update(&t,&f,&r));
    assert(r.people[0].id==2 && r.people[0].items[WS_HELMET].state==WS_UNKNOWN);
    ws_tick(&t,1099,&r); assert(r.observation==APD_MODEL_ERROR && t.count==0);
    assert(ws_init(&t,s)); f=person_frame(1,0); f.people[0].x1=NAN; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,0); f.visibility[0][0]=(ws_visibility)100; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,0); f.equipment[0].kind=APD_HELMET|APD_VEST; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,0); f.equipment[0].kind=128; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,0); f.equipment_count=APD_MAX_EQUIPMENT+1; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,1000); f.received_ms=999; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,1000); f.received_ms=1751; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,1000); assert(ws_update(&t,&f,&r));
    f.frame_id=2; f.captured_ms=999; f.received_ms=999; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,0); assert(ws_update(&t,&f,&r));
    f=person_frame(2,300); f.fault=APD_COMPLIANT; rejected(&t,&f,&r);
    assert(ws_init(&t,s)); f=person_frame(1,0); t.next_id=UINT64_MAX; rejected(&t,&f,&r);
    /* Null backend input cannot preserve an old positive/alarm report. */
    assert(ws_init(&t,s)); f=person_frame(1,0); assert(ws_update(&t,&f,&r));
    f=person_frame(2,300); assert(ws_update(&t,&f,&r));
    assert(r.people[0].items[WS_HELMET].state==WS_PRESENT);
    assert(!ws_update(&t,NULL,&r));
    assert(!t.count && r.observation==APD_MODEL_ERROR && !r.people_count && !r.indicator_track_id);
    assert(ws_init(&t,s)); f=person_frame(1,0); assert(ws_update(&t,&f,&r));
    assert(!ws_update(&t,&f,NULL) && !t.count);
    assert(!ws_update(NULL,&f,&r) && r.observation==APD_MODEL_ERROR && !r.people_count);
    /* Full bounded capacity is valid; no accidental <=/off-by-one rejection. */
    assert(ws_init(&t,s)); memset(&f,0,sizeof(f)); f.frame_id=1;
    f.people_count=APD_MAX_PEOPLE; f.equipment_count=APD_MAX_EQUIPMENT;
    for(size_t i=0;i<APD_MAX_PEOPLE;++i) {
        float x=(float)i*150; f.people[i]=(apd_box){x,0,x+100,200,0.9f};
    }
    for(size_t i=0;i<APD_MAX_EQUIPMENT;++i) {
        float x=(float)(i%APD_MAX_PEOPLE)*150;
        f.equipment[i]=(apd_equipment){{x+10,5,x+60,35,0.9f},APD_HELMET,false};
    }
    assert(ws_update(&t,&f,&r)); assert(r.people_count==APD_MAX_PEOPLE && t.count==APD_MAX_PEOPLE);
    assert(!r.indicator_track_id && !r.alarm_candidate && !ws_outputs_enabled());
    /* Moving camera: never bridge PPE/identity over view changes, even when
     * boxes coincide. Default zero is fixed-view compatibility only. */
    assert(ws_init(&t,s)); f=person_frame(1,0); assert(ws_update(&t,&f,&r));
    f=person_frame(2,300); assert(ws_update(&t,&f,&r));
    uint64_t prior_id=r.people[0].id;
    assert(r.people[0].items[WS_HELMET].state==WS_PRESENT);
    assert(ws_invalidate_camera_view(&t,1,&r));
    assert(r.observation==APD_STARTING && !r.people_count && !t.count);
    assert(!r.alarm_candidate && !r.indicator_track_id && t.previous_frame_id==2);
    f=person_frame(3,600); rejected(&t,&f,&r); /* old buffered epoch */
    f.camera_view_epoch=1; assert(ws_update(&t,&f,&r));
    assert(r.people[0].id!=prior_id && r.people[0].items[WS_HELMET].state==WS_UNKNOWN);
    f=person_frame(4,900); f.camera_view_epoch=1; assert(ws_update(&t,&f,&r));
    assert(r.people[0].items[WS_HELMET].state==WS_PRESENT);
    f=person_frame(5,1200); f.camera_view_epoch=2; f.equipment_count=0;
    assert(ws_update(&t,&f,&r)); assert(r.people[0].items[WS_HELMET].state==WS_UNKNOWN);
    uint64_t changed_id=r.people[0].id;
    for(uint64_t id=6;id<=11;++id) {
        f=person_frame(id,(uint32_t)(id-1)*300); f.camera_view_epoch=2;
        f.camera_view_unstable=true; f.equipment[0].negative=true;
        f.visibility[0][WS_HELMET]=WS_OBSERVABLE;
        assert(ws_update(&t,&f,&r));
        assert(!t.count && r.observation==APD_STARTING && !r.alarm_candidate && !r.people_count);
    }
    f=person_frame(12,3300); f.camera_view_epoch=2;
    assert(ws_update(&t,&f,&r));
    assert(r.people[0].id!=changed_id && r.people[0].items[WS_HELMET].state==WS_UNKNOWN);
    f=person_frame(13,3600); f.camera_view_epoch=2; f.camera_view_unstable=true; f.fault=APD_CAMERA_LOST;
    assert(ws_update(&t,&f,&r)); assert(r.observation==APD_CAMERA_LOST);
    assert(!ws_invalidate_camera_view(&t,2,&r)); assert(r.observation==APD_MODEL_ERROR && !t.count);
    assert(!ws_invalidate_camera_view(&t,1,&r));
    assert(!ws_invalidate_camera_view(NULL,3,&r)); assert(r.observation==APD_MODEL_ERROR);
    assert(!ws_invalidate_camera_view(&t,3,NULL)); assert(!t.count);
    /* Previously confirmed alarm cleared immediately between inference frames. */
    assert(ws_init(&t,s));
    for(uint64_t id=1;id<=4;++id) {
        f=person_frame(id,(uint32_t)(id-1)*500); f.equipment[0].negative=true;
        f.visibility[0][WS_HELMET]=WS_OBSERVABLE; assert(ws_update(&t,&f,&r));
    }
    assert(r.alarm_candidate);
    assert(ws_invalidate_camera_view(&t,1,&r));
    assert(!r.alarm_candidate && !r.indicator_track_id && !r.people_count);
    puts("Workshop C boundary contracts HOST PASS; no hardware");
    return 0;
}
