#include "backend_frame.h"
#include <math.h>
#include <string.h>

bool apd_transform_valid(const apd_frame_transform *t) {
    if (!t || !t->camera_width || !t->camera_height ||
        t->camera_width>8192 || t->camera_height>8192 ||
        !t->input_width || !t->input_height ||
        t->input_width>2048 || t->input_height>2048 ||
        !t->resized_width || !t->resized_height) return false;
    if (t->clockwise_rotation!=0 && t->clockwise_rotation!=90 &&
        t->clockwise_rotation!=180 && t->clockwise_rotation!=270) return false;
    return t->resized_width<=t->input_width && t->resized_height<=t->input_height &&
        t->pad_left<=t->input_width-t->resized_width &&
        t->pad_top<=t->input_height-t->resized_height;
}
static bool box_valid(apd_box b) {
    return isfinite(b.x1) && isfinite(b.y1) && isfinite(b.x2) &&
        isfinite(b.y2) && isfinite(b.confidence) && b.x2>b.x1 && b.y2>b.y1 &&
        b.confidence>=0 && b.confidence<=1;
}
apd_map_status apd_unletterbox_box(const apd_frame_transform *t, apd_box b, apd_box *out) {
    if (!out) return APD_MAP_INVALID;
    memset(out,0,sizeof(*out));
    if (!apd_transform_valid(t) || !box_valid(b) || b.x1<0 || b.y1<0 ||
        b.x2>t->input_width || b.y2>t->input_height) return APD_MAP_INVALID;
    double left=fmax(b.x1,t->pad_left), top=fmax(b.y1,t->pad_top);
    double right=fmin(b.x2,t->pad_left+t->resized_width);
    double bottom=fmin(b.y2,t->pad_top+t->resized_height);
    if (right<=left || bottom<=top) return APD_MAP_PADDING_ONLY;
    bool swap=t->clockwise_rotation==90 || t->clockwise_rotation==270;
    double w=swap ? t->camera_height : t->camera_width;
    double h=swap ? t->camera_width : t->camera_height;
    double x1=(left-t->pad_left)*w/t->resized_width;
    double x2=(right-t->pad_left)*w/t->resized_width;
    double y1=(top-t->pad_top)*h/t->resized_height;
    double y2=(bottom-t->pad_top)*h/t->resized_height;
    *out=(apd_box){(float)x1,(float)y1,(float)x2,(float)y2,b.confidence};
    return box_valid(*out) ? APD_MAP_BOX : APD_MAP_INVALID;
}
apd_map_status apd_inverse_box(const apd_frame_transform *t, apd_box b, apd_box *out) {
    if (!out) return APD_MAP_INVALID;
    apd_box view;
    apd_map_status status=apd_unletterbox_box(t,b,&view);
    memset(out,0,sizeof(*out));
    if (status!=APD_MAP_BOX) return status;
    double x1=view.x1,x2=view.x2,y1=view.y1,y2=view.y2;
    double a=x1,bottom_x=x2,c=y1,d=y2;
    switch (t->clockwise_rotation) {
    case 90: a=y1; bottom_x=y2; c=t->camera_height-x2; d=t->camera_height-x1; break;
    case 180: a=t->camera_width-x2; bottom_x=t->camera_width-x1;
              c=t->camera_height-y2; d=t->camera_height-y1; break;
    case 270: a=t->camera_width-y2; bottom_x=t->camera_width-y1; c=x1; d=x2; break;
    default: break;
    }
    *out=(apd_box){(float)a,(float)c,(float)bottom_x,(float)d,b.confidence};
    return box_valid(*out) ? APD_MAP_BOX : APD_MAP_INVALID;
}
static bool fail(ws_frame *f) {
    uint64_t id=f->frame_id; uint32_t capture=f->captured_ms,receive=f->received_ms;
    memset(f,0,sizeof(*f)); f->frame_id=id; f->captured_ms=capture; f->received_ms=receive;
    f->fault=APD_MODEL_ERROR; return false;
}
bool apd_build_workshop_frame(const apd_frame_transform *t,
    const apd_workshop_label *labels, size_t label_count,
    const apd_raw_detection *detections, size_t count,
    uint64_t id, uint32_t captured, uint32_t received, ws_frame *f) {
    if (!f) return false;
    memset(f,0,sizeof(*f)); f->frame_id=id; f->captured_ms=captured; f->received_ms=received;
    if (!apd_transform_valid(t) || !labels || label_count!=APD_WORKSHOP_CLASSES ||
        count>APD_MAX_RAW_DETECTIONS || (count && !detections)) return fail(f);
    bool seen[APD_WORKSHOP_CLASSES]={false};
    for (size_t i=0;i<label_count;++i) {
        if (labels[i]<APD_LABEL_PERSON || labels[i]>APD_LABEL_NO_HELMET || seen[labels[i]]) return fail(f);
        seen[labels[i]]=true;
    }
    for (size_t i=0;i<count;++i) {
        if (detections[i].class_id>=label_count) return fail(f);
        apd_workshop_label label=labels[detections[i].class_id];
        if (label==APD_LABEL_PERSON) for (size_t k=0;k<WS_ITEMS;++k)
            if (detections[i].visibility[k]<WS_VIS_UNKNOWN ||
                detections[i].visibility[k]>WS_NOT_VISIBLE) return fail(f);
        apd_box box; apd_map_status status=apd_unletterbox_box(t,detections[i].box,&box);
        if (status==APD_MAP_INVALID) return fail(f);
        if (status==APD_MAP_PADDING_ONLY) continue;
        if (label==APD_LABEL_PERSON) {
            if (f->people_count==APD_MAX_PEOPLE) return fail(f);
            size_t n=f->people_count++; f->people[n]=box;
            memcpy(f->visibility[n],detections[i].visibility,sizeof(f->visibility[n]));
        } else {
            if (f->equipment_count==APD_MAX_EQUIPMENT) return fail(f);
            uint8_t kind=APD_HELMET; bool negative=false;
            switch(label) {
            case APD_LABEL_VEST: kind=APD_VEST; break;
            case APD_LABEL_NO_VEST: kind=APD_VEST; negative=true; break;
            case APD_LABEL_SHOES: kind=APD_SHOES; break;
            case APD_LABEL_NO_SHOES: kind=APD_SHOES; negative=true; break;
            case APD_LABEL_NO_HELMET: negative=true; break;
            default: break;
            }
            f->equipment[f->equipment_count++]=(apd_equipment){box,kind,negative};
        }
    }
    return true;
}
