#include "grid_decoder.h"
#include <math.h>
#include <string.h>

static bool contract_valid(const apd_grid_input *in) {
    if (!in || in->contract!=APD_GRID_POSTSIGMOID_I8_NCHW_7 ||
        !in->input_width || !in->input_height || in->input_width>1024 ||
        in->input_height>1024 || !isfinite(in->score_threshold) ||
        in->score_threshold<=0 || in->score_threshold>1 ||
        !isfinite(in->nms_iou) || in->nms_iou<=0 || in->nms_iou>=1) return false;
    for (size_t i=0;i<APD_GRID_HEADS;++i) {
        const apd_grid_head *h=&in->heads[i];
        if (!h->data || !h->grid_width || !h->grid_height ||
            h->grid_width>128 || h->grid_height>128 ||
            (h->pixel_stride!=8 && h->pixel_stride!=16 && h->pixel_stride!=32) ||
            h->grid_width*h->pixel_stride!=in->input_width ||
            h->grid_height*h->pixel_stride!=in->input_height ||
            h->zero_point < -128 || h->zero_point>127 ||
            !isfinite(h->scale) || h->scale<=0 || h->scale>0.0625f ||
            h->row_stride<h->grid_width ||
            h->row_stride>SIZE_MAX/h->grid_height ||
            h->channel_stride<h->row_stride*h->grid_height ||
            h->channel_stride>SIZE_MAX/APD_GRID_CHANNELS) return false;
        /* Avoid overflow even if a caller passes malicious size_t strides. */
        size_t base=(APD_GRID_CHANNELS-1)*h->channel_stride;
        size_t tail=(h->grid_height-1)*h->row_stride+h->grid_width;
        if (base>SIZE_MAX-tail || h->byte_count<base+tail) return false;
        float epsilon=h->scale*0.5f+0.000001f;
        if ((-128-h->zero_point)*h->scale>epsilon ||
            (127-h->zero_point)*h->scale<1-epsilon) return false;
        for (size_t j=0;j<i;++j)
            if (in->heads[j].pixel_stride==h->pixel_stride) return false;
        for (size_t a=0;a<APD_GRID_ANCHORS;++a)
            for (size_t axis=0;axis<2;++axis)
                if (!isfinite(h->anchors[a][axis]) || h->anchors[a][axis]<=0 ||
                    h->anchors[a][axis]>8192) return false;
    }
    return true;
}
static bool probability(const apd_grid_head *h,size_t a,size_t channel,
                         size_t x,size_t y,float *out) {
    size_t offset=(a*(5+APD_WORKSHOP_CLASSES)+channel)*h->channel_stride+
                  y*h->row_stride+x;
    float p=((int)h->data[offset]-h->zero_point)*h->scale;
    float epsilon=h->scale*0.5f+0.000001f;
    if (!isfinite(p) || p < -epsilon || p > 1+epsilon) return false;
    *out=fminf(1,fmaxf(0,p)); return true;
}
static float overlap(apd_box a,apd_box b) {
    float w=fmaxf(0,fminf(a.x2,b.x2)-fmaxf(a.x1,b.x1));
    float h=fmaxf(0,fminf(a.y2,b.y2)-fmaxf(a.y1,b.y1));
    float intersection=w*h;
    float area=(a.x2-a.x1)*(a.y2-a.y1)+(b.x2-b.x1)*(b.y2-b.y1)-intersection;
    return area>0 ? intersection/area : 0;
}
static bool clear_failure(apd_grid_workspace *w,apd_raw_detection *out,
                           size_t capacity,size_t *count) {
    if (w) w->count=0;
    if (count) *count=0;
    if (out && capacity<=APD_MAX_RAW_DETECTIONS) memset(out,0,capacity*sizeof(*out));
    return false;
}
bool apd_grid_decode(const apd_grid_input *in,apd_grid_workspace *w,
                     apd_raw_detection *out,size_t capacity,size_t *count) {
    if (count) *count=0;
    if (w) w->count=0;
    if (!w || !out || !count || !capacity || capacity>APD_MAX_RAW_DETECTIONS ||
        !contract_valid(in)) return clear_failure(w,out,capacity,count);
    memset(out,0,capacity*sizeof(*out));
    for (size_t hi=0;hi<APD_GRID_HEADS;++hi) {
        const apd_grid_head *h=&in->heads[hi];
        for (size_t a=0;a<APD_GRID_ANCHORS;++a)
            for (size_t y=0;y<h->grid_height;++y)
                for (size_t x=0;x<h->grid_width;++x) {
                    float p[5+APD_WORKSHOP_CLASSES];
                    /* Validate every logical value, even below threshold. A
                     * logits/layout mismatch must not hide behind low scores.
                     * Physical padding bytes are deliberately not interpreted. */
                    for (size_t c=0;c<5+APD_WORKSHOP_CLASSES;++c)
                        if (!probability(h,a,c,x,y,&p[c]))
                            return clear_failure(w,out,capacity,count);
                    size_t cls=0;
                    for (size_t c=1;c<APD_WORKSHOP_CLASSES;++c)
                        if (p[5+c]>p[5+cls]) cls=c;
                    float score=p[4]*p[5+cls];
                    if (score<in->score_threshold) continue;
                    float cx=(p[0]*2-0.5f+(float)x)*h->pixel_stride;
                    float cy=(p[1]*2-0.5f+(float)y)*h->pixel_stride;
                    float bw=p[2]*p[2]*4*h->anchors[a][0];
                    float bh=p[3]*p[3]*4*h->anchors[a][1];
                    apd_box b={fmaxf(0,cx-bw*0.5f),fmaxf(0,cy-bh*0.5f),
                        fminf(in->input_width,cx+bw*0.5f),
                        fminf(in->input_height,cy+bh*0.5f),score};
                    if (!isfinite(b.x1) || !isfinite(b.x2) || !isfinite(b.y1) ||
                        !isfinite(b.y2)) return clear_failure(w,out,capacity,count);
                    if (b.x2<=b.x1 || b.y2<=b.y1) continue;
                    if (w->count==APD_GRID_MAX_CANDIDATES)
                        return clear_failure(w,out,capacity,count);
                    w->candidates[w->count]=(apd_grid_candidate){b,(uint8_t)cls,false};
                    /* Bounded stable descending insertion; indices not boxes. */
                    size_t pos=w->count;
                    while (pos>0 && w->candidates[w->order[pos-1]].box.confidence<score) {
                        w->order[pos]=w->order[pos-1]; --pos;
                    }
                    w->order[pos]=(uint16_t)w->count; ++w->count;
                }
    }
    for (size_t i=0;i<w->count;++i) {
        apd_grid_candidate *c=&w->candidates[w->order[i]];
        if (c->suppressed) continue;
        if (*count==capacity) return clear_failure(w,out,capacity,count);
        out[*count].box=c->box; out[*count].class_id=c->class_id;
        /* memset leaves visibility WS_VIS_UNKNOWN, not OBSERVABLE. */
        ++*count;
        for (size_t j=i+1;j<w->count;++j) {
            apd_grid_candidate *other=&w->candidates[w->order[j]];
            if (!other->suppressed && other->class_id==c->class_id &&
                overlap(c->box,other->box)>in->nms_iou) other->suppressed=true;
        }
    }
    return true;
}
