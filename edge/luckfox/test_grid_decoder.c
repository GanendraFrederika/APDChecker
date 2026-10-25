#include "grid_decoder.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static int8_t data[3][36*16];
static apd_grid_workspace workspace;
static apd_grid_input fixture(uint32_t size) {
    apd_grid_input in; memset(&in,0,sizeof(in)); memset(data,-128,sizeof(data));
    in.contract=1; in.input_width=size; in.input_height=size;
    in.score_threshold=0.35f; in.nms_iou=0.45f;
    for(size_t i=0;i<3;++i) {
        apd_grid_head *h=&in.heads[i]; uint32_t stride=8u<<i;
        h->data=data[i]; h->byte_count=sizeof(data[i]);
        h->grid_width=size/stride; h->grid_height=size/stride;
        h->row_stride=h->grid_width; h->channel_stride=h->row_stride*h->grid_height;
        h->pixel_stride=stride; h->zero_point=-128; h->scale=1.0f/255.0f;
        for(size_t a=0;a<3;++a) h->anchors[a][0]=h->anchors[a][1]=8;
    }
    return in;
}
static void set(apd_grid_input *in,size_t head,size_t anchor,size_t x,size_t y,
                 size_t channel,int8_t value) {
    apd_grid_head *h=&in->heads[head];
    data[head][(anchor*12+channel)*h->channel_stride+y*h->row_stride+x]=value;
}
static void detection(apd_grid_input *in,size_t head,size_t anchor,size_t x,
                       size_t y,size_t cls) {
    for(size_t c=0;c<4;++c) set(in,head,anchor,x,y,c,0);
    set(in,head,anchor,x,y,4,127); set(in,head,anchor,x,y,5+cls,127);
}
static void failed(apd_grid_input *in) {
    apd_raw_detection out[72]; size_t count=99; memset(out,0x55,sizeof(out));
    assert(!apd_grid_decode(in,&workspace,out,72,&count)); assert(count==0);
    assert(workspace.count==0);
    for(size_t i=0;i<72;++i) assert(out[i].box.confidence==0);
}
void test_grid_vectors(void);
int main(void) {
    apd_raw_detection out[72]; size_t count=999; apd_grid_input in=fixture(32);
    assert(apd_grid_decode(&in,&workspace,out,72,&count)); assert(count==0);
    detection(&in,0,0,1,1,1); detection(&in,0,1,1,1,1);
    detection(&in,0,2,1,1,2); /* identical negative box NOT suppressed */
    assert(apd_grid_decode(&in,&workspace,out,72,&count)); assert(count==2);
    assert(out[0].class_id==1 && out[1].class_id==2);
    assert(out[0].box.confidence==1);
    set(&in,0,2,1,1,5+1,127); /* tied class scores: lower ID wins */
    assert(apd_grid_decode(&in,&workspace,out,72,&count)); assert(count==1);
    count=99; assert(!apd_grid_decode(&in,&workspace,NULL,72,&count)); assert(count==0);
    failed(NULL);
#define BAD(statement) do {in=fixture(32); statement; failed(&in);} while(0)
    BAD(in.contract=2); BAD(in.input_width=0); BAD(in.input_height=2048);
    BAD(in.score_threshold=NAN); BAD(in.score_threshold=0); BAD(in.nms_iou=1);
    BAD(in.heads[0].data=NULL); BAD(in.heads[0].byte_count=1);
    BAD(in.heads[0].row_stride=3); BAD(in.heads[0].row_stride=SIZE_MAX);
    BAD(in.heads[0].channel_stride=SIZE_MAX); BAD(in.heads[0].channel_stride=15);
    BAD(in.heads[0].grid_width=0); BAD(in.heads[0].grid_height=129);
    BAD(in.heads[0].pixel_stride=7); BAD(in.heads[1]=in.heads[0]);
    BAD(in.heads[0].zero_point=-129); BAD(in.heads[0].scale=0);
    BAD(in.heads[0].scale=INFINITY); BAD(in.heads[0].scale=0.1f);
    BAD(in.heads[0].scale=0.0001f); BAD(in.heads[0].anchors[0][0]=-1);
    BAD(in.heads[0].anchors[0][0]=NAN);
    BAD(in.heads[0].zero_point=0); /* -128 background is invalid probability */
    BAD(in.heads[0].scale=1.0f/128; data[0][0]=127); /* invalid even low objectness */
#undef BAD
    /* Exact minimum readable last logical byte is enough, no overread required. */
    in=fixture(32); in.heads[0].byte_count=36*16;
    assert(apd_grid_decode(&in,&workspace,out,72,&count));
    --in.heads[0].byte_count; failed(&in);
    /* NMS output capacity failure clears partial output. */
    in=fixture(32); detection(&in,0,0,0,0,1); detection(&in,0,1,0,0,2);
    memset(out,0x55,sizeof(out));
    assert(!apd_grid_decode(&in,&workspace,out,1,&count));
    assert(count==0 && out[0].box.confidence==0);
    /* >72 distinct survivors below 256 candidate limit: no output top-K. */
    static int8_t many[3][36*64]; memset(many,-128,sizeof(many));
    in=fixture(64);
    for(size_t i=0;i<3;++i) {
        apd_grid_head *h=&in.heads[i]; h->data=many[i]; h->byte_count=sizeof(many[i]);
        for(size_t a=0;a<3;++a) h->anchors[a][0]=h->anchors[a][1]=1;
        for(size_t y=0;y<h->grid_height;++y) for(size_t x=0;x<h->grid_width;++x) {
            for(size_t c=0;c<4;++c) many[i][c*h->channel_stride+y*h->row_stride+x]=0;
            many[i][4*h->channel_stride+y*h->row_stride+x]=127;
            many[i][5*h->channel_stride+y*h->row_stride+x]=127;
        }
    }
    failed(&in); /* 64+16+4 boxes at distinct centers */
    /* Candidate limit before NMS: don't truncate a crowded/high-score frame. */
    static int8_t crowded[3][36*144]; memset(crowded,-128,sizeof(crowded));
    in=fixture(96);
    for(size_t i=0;i<3;++i) {
        apd_grid_head *h=&in.heads[i]; h->data=crowded[i]; h->byte_count=sizeof(crowded[i]);
        for(size_t a=0;a<3;++a) for(size_t y=0;y<h->grid_height;++y)
            for(size_t x=0;x<h->grid_width;++x) {
                for(size_t c=0;c<4;++c) crowded[i][(a*12+c)*h->channel_stride+y*h->row_stride+x]=0;
                crowded[i][(a*12+4)*h->channel_stride+y*h->row_stride+x]=127;
                crowded[i][(a*12+5)*h->channel_stride+y*h->row_stride+x]=127;
            }
    }
    failed(&in);
    /* Exactly 256 candidates admitted; 257th rejected even if NMS would
     * reduce all to one. Exercise the last order/workspace slot explicitly. */
    memset(crowded,-128,sizeof(crowded));
    for(size_t i=0;i<3;++i) for(size_t a=0;a<3;++a)
        in.heads[i].anchors[a][0]=in.heads[i].anchors[a][1]=8192;
    size_t created=0;
    for(size_t i=0;i<3;++i) {
        apd_grid_head *h=&in.heads[i];
        for(size_t a=0;a<3;++a) for(size_t y=0;y<h->grid_height;++y)
            for(size_t x=0;x<h->grid_width;++x) {
                if(created>=256) continue;
                for(size_t c=0;c<4;++c) crowded[i][(a*12+c)*h->channel_stride+y*h->row_stride+x]=0;
                crowded[i][(a*12+4)*h->channel_stride+y*h->row_stride+x]=127;
                crowded[i][(a*12+5)*h->channel_stride+y*h->row_stride+x]=127;
                ++created;
            }
    }
    assert(apd_grid_decode(&in,&workspace,out,72,&count));
    assert(workspace.count==256 && count==1);
    /* First unfilled cell in head0 anchor1: 144 + 112 = 256. */
    apd_grid_head *extra=&in.heads[0]; size_t x_extra=4,y_extra=9;
    for(size_t c=0;c<4;++c) crowded[0][(12+c)*extra->channel_stride+y_extra*extra->row_stride+x_extra]=0;
    crowded[0][16*extra->channel_stride+y_extra*extra->row_stride+x_extra]=127;
    crowded[0][17*extra->channel_stride+y_extra*extra->row_stride+x_extra]=127;
    failed(&in);
    /* Builder/tracker integration: explicit no_helmet with UNKNOWN visibility
     * never becomes confirmed ABSENT just because decoder returned a box. */
    in=fixture(32); in.heads[2].anchors[0][0]=32; in.heads[2].anchors[0][1]=32;
    detection(&in,2,0,0,0,0); detection(&in,0,0,1,0,6);
    assert(apd_grid_decode(&in,&workspace,out,72,&count)); assert(count==2);
    apd_workshop_label labels[7]={APD_LABEL_PERSON,APD_LABEL_VEST,APD_LABEL_NO_VEST,
        APD_LABEL_SHOES,APD_LABEL_NO_SHOES,APD_LABEL_HELMET,APD_LABEL_NO_HELMET};
    apd_frame_transform transform={32,32,32,32,32,32,0,0,0};
    ws_tracker tracker; ws_report report; ws_frame frame;
    assert(ws_init(&tracker,ws_defaults()));
    for(uint32_t n=1;n<=10;++n) {
        assert(apd_build_workshop_frame(&transform,labels,7,out,count,n,n*333,n*333,&frame));
        assert(frame.people_count==1 && frame.equipment_count==1);
        assert(ws_update(&tracker,&frame,&report));
        assert(report.people_count==1 && !report.alarm_candidate);
        assert(report.people[0].items[WS_HELMET].state!=WS_ABSENT);
    }
    /* Model fault invalidates accumulated tracker state at the next update. */
    frame.fault=APD_MODEL_ERROR; ++frame.frame_id; frame.captured_ms+=333;
    frame.received_ms=frame.captured_ms;
    assert(ws_update(&tracker,&frame,&report));
    assert(report.observation==APD_MODEL_ERROR && report.retained_tracks==0);
    assert(!report.alarm_candidate && !ws_outputs_enabled());
    test_grid_vectors();
    printf("Grid boundary/integration HOST PASS; workspace=%zu bytes; NOT RV1103/NPU\n",sizeof(workspace));
    return 0;
}
