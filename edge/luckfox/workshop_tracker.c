#include "workshop_tracker.h"
#include <math.h>
#include <string.h>

static float maxf(float a, float b) { return a > b ? a : b; }
static float minf(float a, float b) { return a < b ? a : b; }
static float area(apd_box b) { return (b.x2-b.x1)*(b.y2-b.y1); }
static float intersect(apd_box a, apd_box b) {
    return maxf(0,minf(a.x2,b.x2)-maxf(a.x1,b.x1))*
           maxf(0,minf(a.y2,b.y2)-maxf(a.y1,b.y1));
}
static float iou(apd_box a, apd_box b) {
    float x = intersect(a,b);
    return x/(area(a)-x+area(b));
}
static bool box_valid(apd_box b) {
    return isfinite(b.x1) && isfinite(b.y1) && isfinite(b.x2) &&
        isfinite(b.y2) && isfinite(b.confidence) && b.x2>b.x1 && b.y2>b.y1 &&
        b.confidence>=0 && b.confidence<=1 && isfinite(area(b)) && area(b)>0;
}
static bool probability(float value) { return isfinite(value) && value>0 && value<=1; }
static bool duration(uint32_t value) { return value>0 && value<=INT32_MAX; }
static void clear_report(ws_report *r, apd_observation fault) {
    memset(r,0,sizeof(*r)); r->observation=fault;
}
static bool reject(ws_tracker *t, ws_report *r) {
    t->count=0; clear_report(r,APD_MODEL_ERROR); return false;
}
ws_settings ws_defaults(void) {
    ws_settings s={0.4f,0.3f,0.2f,250,1500,2000,1000,750,750,2,3};
    return s;
}
bool ws_init(ws_tracker *t, ws_settings s) {
    if (!t) return false;
    memset(t,0,sizeof(*t));
    if (!probability(s.confidence) || !probability(s.match_iou) ||
        !probability(s.overlap_fraction) || !duration(s.present_ms) ||
        !duration(s.absent_ms) || !duration(s.evidence_ttl_ms) ||
        !duration(s.lost_ttl_ms) || !duration(s.max_gap_ms) ||
        !duration(s.max_frame_age_ms) || s.present_samples<2 || s.absent_samples<2) return false;
    t->settings=s; t->next_id=1; return true;
}
static void observe(ws_memory *m, ws_item_state raw, float confidence,
                    uint32_t now, const ws_settings *s) {
    if (m->has_observed && now-m->observed_ms>=s->evidence_ttl_ms) {
        m->state=WS_UNKNOWN; m->has_observed=false; m->confidence=0;
    }
    if (raw==WS_UNKNOWN || raw==WS_CONFLICT) {
        m->has_candidate=false; m->candidate=WS_UNKNOWN; m->samples=0;
        if (raw==WS_CONFLICT) { m->state=WS_UNKNOWN; m->has_observed=false; m->confidence=0; }
        return;
    }
    if (m->state!=WS_UNKNOWN && m->state!=raw) {
        m->state=WS_UNKNOWN; m->has_observed=false; m->confidence=0;
    }
    if (!m->has_candidate || m->candidate!=raw || now-m->previous_ms>s->max_gap_ms) {
        m->candidate=raw; m->since_ms=now; m->samples=1;
    } else if (m->samples<UINT16_MAX) ++m->samples;
    m->has_candidate=true; m->previous_ms=now;
    uint32_t delay=raw==WS_PRESENT ? s->present_ms : s->absent_ms;
    uint16_t samples=raw==WS_PRESENT ? s->present_samples : s->absent_samples;
    if (m->samples>=samples && now-m->since_ms>=delay) m->state=raw;
    if (m->state==raw) { m->observed_ms=now; m->has_observed=true; m->confidence=confidence; }
}
static int item_index(uint8_t kind) {
    if (kind==APD_VEST) return WS_VEST;
    if (kind==APD_SHOES) return WS_SHOES;
    if (kind==APD_HELMET) return WS_HELMET;
    return -1;
}
bool ws_invalidate_camera_view(ws_tracker *t, uint64_t epoch, ws_report *r) {
    if (!t || !r) {
        if (t) t->count=0;
        if (r) clear_report(r,APD_MODEL_ERROR);
        return false;
    }
    if (!t->next_id || epoch<=t->camera_view_epoch) return reject(t,r);
    t->count=0; t->camera_view_epoch=epoch;
    clear_report(r,APD_STARTING); return true;
}
bool ws_update(ws_tracker *t, const ws_frame *f, ws_report *r) {
    if (!t || !f || !r) {
        if (t) t->count=0;
        if (r) clear_report(r,APD_MODEL_ERROR);
        return false;
    }
    clear_report(r,APD_UNKNOWN);
    if (!t->next_id || !duration(t->settings.max_frame_age_ms) || t->count>APD_MAX_PEOPLE) return reject(t,r);
    if (f->camera_view_epoch<t->camera_view_epoch) return reject(t,r);
    uint32_t age=f->received_ms-f->captured_ms;
    if (age>INT32_MAX || age>t->settings.max_frame_age_ms) return reject(t,r);
    if (t->has_previous) {
        uint32_t gap=f->captured_ms-t->previous_ms;
        if (f->frame_id<=t->previous_frame_id || !gap || gap>INT32_MAX) return reject(t,r);
        if (gap>t->settings.max_gap_ms) t->count=0;
    }
    t->has_previous=true; t->previous_ms=f->captured_ms; t->previous_frame_id=f->frame_id;
    if (f->camera_view_epoch!=t->camera_view_epoch) {
        t->count=0; t->camera_view_epoch=f->camera_view_epoch;
    }
    if (f->fault!=APD_UNKNOWN) {
        if (f->fault!=APD_CAMERA_LOST && f->fault!=APD_MODEL_ERROR && f->fault!=APD_STARTING) return reject(t,r);
        t->count=0; clear_report(r,f->fault); return true;
    }
    if (f->camera_view_unstable) {
        t->count=0; clear_report(r,APD_STARTING); return true;
    }
    if (f->people_count>APD_MAX_PEOPLE || f->equipment_count>APD_MAX_EQUIPMENT) return reject(t,r);
    size_t input[APD_MAX_PEOPLE], n=0;
    for (size_t i=0;i<f->people_count;++i) {
        if (!box_valid(f->people[i])) return reject(t,r);
        for (size_t k=0;k<WS_ITEMS;++k)
            if (f->visibility[i][k]<WS_VIS_UNKNOWN || f->visibility[i][k]>WS_NOT_VISIBLE) return reject(t,r);
        if (f->people[i].confidence>=t->settings.confidence) input[n++]=i;
    }
    for (size_t i=0;i<f->equipment_count;++i) {
        uint8_t kind=f->equipment[i].kind;
        if (!box_valid(f->equipment[i].box) || !kind || (kind&(kind-1u)) || (kind&~APD_ALL_PPE)) return reject(t,r);
    }
    ws_track old[APD_MAX_PEOPLE]; size_t old_count=0;
    for (size_t j=0;j<t->count;++j) {
        uint32_t elapsed=f->captured_ms-t->tracks[j].last_seen_ms;
        if (elapsed>INT32_MAX) return reject(t,r);
        if (elapsed<t->settings.lost_ttl_ms) old[old_count++]=t->tracks[j];
    }
    bool match[APD_MAX_PEOPLE][APD_MAX_PEOPLE]={{false}};
    bool uncertain[APD_MAX_PEOPLE]={false}, retired[APD_MAX_PEOPLE]={false}, used[APD_MAX_PEOPLE]={false};
    size_t matches[APD_MAX_PEOPLE]={0}, reverse[APD_MAX_PEOPLE]={0};
    for (size_t i=0;i<n;++i) for (size_t j=0;j<old_count;++j) {
        match[i][j]=iou(f->people[input[i]],old[j].box)>=t->settings.match_iou;
        if (match[i][j]) { ++matches[i]; ++reverse[j]; }
    }
    for (size_t i=0;i<n;++i) {
        if (matches[i]>1) uncertain[i]=true;
        for (size_t j=0;j<old_count;++j) if (match[i][j] && reverse[j]>1) uncertain[i]=true;
        for (size_t j=0;j<i;++j) {
            apd_box a=f->people[input[i]], b=f->people[input[j]];
            if (intersect(a,b)/minf(area(a),area(b))>=t->settings.overlap_fraction)
                uncertain[i]=uncertain[j]=true;
        }
    }
    for (size_t i=0;i<n;++i) if (uncertain[i])
        for (size_t j=0;j<old_count;++j) if (match[i][j]) retired[j]=true;
    ws_track current[APD_MAX_PEOPLE]; memset(current,0,sizeof(current));
    for (size_t i=0;i<n;++i) {
        bool found=false;
        for (size_t j=0;j<old_count;++j) if (!uncertain[i] && matches[i]==1 && match[i][j] && !retired[j]) {
            current[i]=old[j]; used[j]=true; found=true; break;
        }
        if (!found) {
            if (t->next_id==UINT64_MAX) return reject(t,r);
            current[i].id=t->next_id++;
        }
        current[i].box=f->people[input[i]]; current[i].last_seen_ms=f->captured_ms;
    }
    /* Invisible handles retained with EMPTY evidence; current people priority. */
    t->count=0;
    for (size_t j=0;j<old_count && t->count<APD_MAX_PEOPLE-n;++j) if (!used[j] && !retired[j]) {
        memset(old[j].items,0,sizeof(old[j].items)); t->tracks[t->count++]=old[j];
    }
    bool positive[APD_MAX_PEOPLE][WS_ITEMS]={{false}}, negative[APD_MAX_PEOPLE][WS_ITEMS]={{false}};
    float positive_conf[APD_MAX_PEOPLE][WS_ITEMS]={{0}}, negative_conf[APD_MAX_PEOPLE][WS_ITEMS]={{0}};
    for (size_t j=0;j<f->equipment_count;++j) {
        apd_equipment gear=f->equipment[j]; int k=item_index(gear.kind);
        if (k<0 || gear.box.confidence<t->settings.confidence) continue;
        float cx=(gear.box.x1+gear.box.x2)/2, cy=(gear.box.y1+gear.box.y2)/2;
        size_t possible=0, candidate=0;
        for (size_t i=0;i<n;++i) {
            apd_box p=current[i].box;
            if (cx<p.x1 || cx>p.x2 || cy<p.y1 || cy>p.y2) continue;
            float y=(cy-p.y1)/(p.y2-p.y1);
            if ((k==WS_HELMET && y>0.55f) || (k==WS_SHOES && y<0.5f) ||
                (k==WS_VEST && (y<0.15f || y>0.8f))) continue;
            candidate=i; ++possible;
        }
        if (possible!=1 || uncertain[candidate]) { ++r->unassigned_equipment; continue; }
        if (gear.negative) {
            negative[candidate][k]=true; negative_conf[candidate][k]=maxf(negative_conf[candidate][k],gear.box.confidence);
        } else {
            positive[candidate][k]=true; positive_conf[candidate][k]=maxf(positive_conf[candidate][k],gear.box.confidence);
        }
    }
    bool violation=false, unknown=false;
    for (size_t i=0;i<n;++i) {
        ws_person_result *p=&r->people[i]; p->id=current[i].id; p->box=current[i].box;
        p->identity_ambiguous=uncertain[i]; bool absent=false, all_present=true;
        for (size_t k=0;k<WS_ITEMS;++k) {
            ws_visibility vis=f->visibility[input[i]][k]; ws_item_state raw=WS_UNKNOWN; float confidence=0;
            if (!uncertain[i] && vis!=WS_NOT_VISIBLE) {
                if (positive[i][k] && negative[i][k]) raw=WS_CONFLICT;
                else if (positive[i][k]) { raw=WS_PRESENT; confidence=positive_conf[i][k]; }
                else if (negative[i][k] && vis==WS_OBSERVABLE) { raw=WS_ABSENT; confidence=negative_conf[i][k]; }
            }
            ws_memory *m=&current[i].items[k]; observe(m,raw,confidence,f->captured_ms,&t->settings);
            ws_item_result *item=&p->items[k]; item->state=m->state; item->observation=raw;
            item->visibility=vis; item->confidence=m->confidence; item->has_observed=m->has_observed;
            item->observed_ms=m->observed_ms;
            item->source=(m->has_observed && m->observed_ms==f->captured_ms && m->state==raw) ? WS_FRESH :
                          m->state!=WS_UNKNOWN ? WS_CACHED : WS_NONE;
            if (m->state==WS_ABSENT) absent=true;
            if (m->state!=WS_PRESENT) all_present=false;
            if (m->state==WS_ABSENT && item->source==WS_FRESH) p->alarm_candidate=true;
        }
        p->observation=absent ? APD_VIOLATION : all_present ? APD_COMPLIANT : APD_UNKNOWN;
        violation=violation || absent; unknown=unknown || p->observation==APD_UNKNOWN;
        r->alarm_candidate=r->alarm_candidate || p->alarm_candidate;
        t->tracks[t->count++]=current[i];
    }
    r->people_count=n; r->retained_tracks=t->count;
    r->observation=violation ? APD_VIOLATION : (unknown || r->unassigned_equipment) ? APD_UNKNOWN : n ? APD_COMPLIANT : APD_NO_PERSON;
    for (size_t i=0;i<n;++i) if ((f->selected_track_id && r->people[i].id==f->selected_track_id) || (!f->selected_track_id && n==1)) {
        r->indicator_track_id=r->people[i].id;
        for (size_t k=0;k<WS_ITEMS;++k) r->indicators[k]=r->people[i].items[k].state;
    }
    return true;
}
void ws_tick(ws_tracker *t, uint32_t now, ws_report *r) {
    if (!t || !r) return;
    if (!t->has_previous) { clear_report(r,APD_STARTING); return; }
    uint32_t age=now-t->previous_ms;
    if (age>INT32_MAX) { t->count=0; clear_report(r,APD_MODEL_ERROR); }
    else if (age>=t->settings.max_frame_age_ms) { t->count=0; clear_report(r,APD_CAMERA_LOST); }
}
bool ws_outputs_enabled(void) { return false; }
