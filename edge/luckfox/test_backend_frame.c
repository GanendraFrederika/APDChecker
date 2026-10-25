/* HOST-only integration contracts; no RK-MPI/RKNN/MCU mocks claiming deployment. */
#include "backend_frame.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
void test_backend_vectors(void);
static const apd_workshop_label labels[APD_WORKSHOP_CLASSES]={
    APD_LABEL_NO_HELMET,APD_LABEL_PERSON,APD_LABEL_NO_VEST,
    APD_LABEL_SHOES,APD_LABEL_HELMET,APD_LABEL_VEST,APD_LABEL_NO_SHOES};
static void fault(const ws_frame *f) {
    assert(f->fault==APD_MODEL_ERROR && !f->people_count && !f->equipment_count);
}
int main(void) {
    apd_frame_transform t={640,480,320,320,320,240,0,40,0};
    apd_box box={10,10,30,30,0.9f},out;
    assert(apd_inverse_box(&t,box,&out)==APD_MAP_PADDING_ONLY);
    box=(apd_box){10,20,30,50,0.9f};
    assert(apd_inverse_box(&t,box,&out)==APD_MAP_BOX);
    assert(out.x1==20 && out.y1==0 && out.x2==60 && out.y2==20);
    assert(!apd_transform_valid(NULL));
    apd_frame_transform invalid=t; invalid.pad_top=81;
    assert(!apd_transform_valid(&invalid)); invalid=t; invalid.clockwise_rotation=45;
    assert(!apd_transform_valid(&invalid)); invalid=t; invalid.resized_width=0;
    assert(!apd_transform_valid(&invalid)); invalid=t; invalid.input_width=UINT32_MAX;
    assert(!apd_transform_valid(&invalid));
    box.x1=NAN; assert(apd_inverse_box(&t,box,&out)==APD_MAP_INVALID);
    box=(apd_box){-1,40,30,50,0.9f}; assert(apd_inverse_box(&t,box,&out)==APD_MAP_INVALID);
    box=(apd_box){0,40,321,50,0.9f}; assert(apd_inverse_box(&t,box,&out)==APD_MAP_INVALID);
    box=(apd_box){10,40,30,50,INFINITY}; assert(apd_inverse_box(&t,box,&out)==APD_MAP_INVALID);
    apd_raw_detection raw[APD_MAX_RAW_DETECTIONS]; memset(raw,0,sizeof(raw));
    ws_frame f;
    raw[0].box=(apd_box){0,40,50,140,0.9f}; raw[0].class_id=1;
    raw[0].visibility[WS_SHOES]=WS_NOT_VISIBLE;
    raw[1].box=(apd_box){5,42.5f,30,57.5f,0.9f}; raw[1].class_id=4;
    assert(apd_build_workshop_frame(&t,labels,7,raw,2,12,100,110,&f));
    assert(f.frame_id==12 && f.captured_ms==100 && f.received_ms==110);
    assert(f.people_count==1 && f.equipment_count==1);
    assert(f.visibility[0][WS_SHOES]==WS_NOT_VISIBLE);
    assert(f.equipment[0].kind==APD_HELMET && !f.equipment[0].negative);
    /* An upside-down RAW sensor must be kept in the upright rotated tracking
     * view. Inverting rotation before body-zone association loses helmets. */
    t=(apd_frame_transform){640,480,320,320,320,240,0,40,180};
    ws_tracker tracker; ws_report report; assert(ws_init(&tracker,ws_defaults()));
    assert(apd_build_workshop_frame(&t,labels,7,raw,2,1,0,0,&f));
    assert(ws_update(&tracker,&f,&report));
    assert(apd_build_workshop_frame(&t,labels,7,raw,2,2,300,300,&f));
    assert(ws_update(&tracker,&f,&report));
    assert(report.people[0].items[WS_HELMET].state==WS_PRESENT);
    assert(report.people[0].items[WS_SHOES].state==WS_UNKNOWN);
    /* All seven explicit IDs, arbitrary ordering; no_* requires OBSERVABLE. */
    for (size_t i=0;i<7;++i) {raw[i].class_id=i; raw[i].box=(apd_box){10,50,20,60,0.9f};}
    assert(apd_build_workshop_frame(&t,labels,7,raw,7,3,600,600,&f));
    assert(f.people_count==1 && f.equipment_count==6);
    size_t negatives=0; for(size_t i=0;i<6;++i) negatives+=f.equipment[i].negative ? 1u : 0u;
    assert(negatives==3);
    apd_workshop_label duplicate[7]; memcpy(duplicate,labels,sizeof(duplicate)); duplicate[0]=duplicate[1];
    assert(!apd_build_workshop_frame(&t,duplicate,7,raw,7,4,700,700,&f)); fault(&f);
    duplicate[0]=(apd_workshop_label)100;
    assert(!apd_build_workshop_frame(&t,duplicate,7,raw,7,4,700,700,&f)); fault(&f);
    assert(!apd_build_workshop_frame(&t,labels,6,raw,7,4,700,700,&f)); fault(&f);
    assert(!apd_build_workshop_frame(&t,labels,7,NULL,1,4,700,700,&f)); fault(&f);
    assert(!apd_build_workshop_frame(&t,labels,7,raw,APD_MAX_RAW_DETECTIONS+1,4,700,700,&f)); fault(&f);
    raw[0].class_id=7;
    assert(!apd_build_workshop_frame(&t,labels,7,raw,7,4,700,700,&f)); fault(&f);
    raw[0].class_id=1; raw[0].visibility[0]=(ws_visibility)123;
    assert(!apd_build_workshop_frame(&t,labels,7,raw,7,4,700,700,&f)); fault(&f);
    raw[0].visibility[0]=WS_VIS_UNKNOWN;
    for(size_t i=0;i<APD_MAX_RAW_DETECTIONS;++i) {raw[i].class_id=1; raw[i].box=box=(apd_box){0,40,50,140,0.9f};}
    assert(!apd_build_workshop_frame(&t,labels,7,raw,9,4,700,700,&f)); fault(&f);
    for(size_t i=0;i<APD_MAX_RAW_DETECTIONS;++i) raw[i].class_id=4;
    assert(!apd_build_workshop_frame(&t,labels,7,raw,65,4,700,700,&f)); fault(&f);
    /* Partial append followed by a malformed detection must leave no evidence. */
    raw[0].class_id=1; raw[1].box.x1=NAN;
    assert(!apd_build_workshop_frame(&t,labels,7,raw,2,4,700,700,&f)); fault(&f);
    assert(f.frame_id==4 && f.captured_ms==700 && f.received_ms==700);
    assert(ws_update(&tracker,&f,&report));
    assert(report.observation==APD_MODEL_ERROR && tracker.count==0 && !report.alarm_candidate);
    /* Post-filter visibility stays aligned with original person detections. */
    t=(apd_frame_transform){640,480,320,320,320,240,0,40,0};
    memset(raw,0,sizeof(raw));
    raw[0].box=(apd_box){100,40,150,140,0.1f}; raw[0].class_id=1;
    raw[0].visibility[WS_HELMET]=WS_OBSERVABLE;
    raw[1].box=(apd_box){0,40,50,140,0.9f}; raw[1].class_id=1;
    raw[1].visibility[WS_HELMET]=WS_NOT_VISIBLE;
    raw[2].box=(apd_box){5,42.5f,30,57.5f,0.9f}; raw[2].class_id=0;
    assert(ws_init(&tracker,ws_defaults()));
    for(uint32_t time=0;time<=1500;time+=500) {
        assert(apd_build_workshop_frame(&t,labels,7,raw,3,time/500+1,time,time,&f));
        assert(ws_update(&tracker,&f,&report));
        assert(report.people_count==1 && !report.alarm_candidate);
        assert(report.people[0].items[WS_HELMET].state==WS_UNKNOWN);
        assert(report.people[0].items[WS_HELMET].visibility==WS_NOT_VISIBLE);
    }
    raw[1].visibility[WS_HELMET]=WS_OBSERVABLE;
    for(uint32_t time=2000;time<=3500;time+=500) {
        assert(apd_build_workshop_frame(&t,labels,7,raw,3,time/500+1,time,time,&f));
        assert(ws_update(&tracker,&f,&report));
    }
    assert(report.people[0].items[WS_HELMET].state==WS_ABSENT);
    assert(report.alarm_candidate);
    /* A new positive cancels old absence immediately, then requires dwell. */
    raw[2].class_id=4;
    assert(apd_build_workshop_frame(&t,labels,7,raw,3,9,3800,3800,&f));
    assert(ws_update(&tracker,&f,&report));
    assert(report.people[0].items[WS_HELMET].state==WS_UNKNOWN && !report.alarm_candidate);
    assert(apd_build_workshop_frame(&t,labels,7,raw,3,10,4100,4100,&f));
    assert(ws_update(&tracker,&f,&report));
    assert(report.people[0].items[WS_HELMET].state==WS_PRESENT && !report.alarm_candidate);
    /* Padding-only detections do not become evidence in the camera view. */
    raw[3].box=(apd_box){0,0,50,30,0.9f}; raw[3].class_id=4;
    assert(apd_build_workshop_frame(&t,labels,7,raw,4,11,4400,4400,&f));
    assert(f.equipment_count==1);
    test_backend_vectors(); assert(!ws_outputs_enabled());
    puts("Backend frame contract HOST PASS; no camera/NPU/UART");
    return 0;
}
