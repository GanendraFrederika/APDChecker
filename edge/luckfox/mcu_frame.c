#include "mcu_frame.h"
#include <stdio.h>
#include <string.h>
#include <inttypes.h>

static bool valid_session(const char *s) {
    if(!s || strlen(s)!=8) return false;
    bool nonzero=false;
    for(size_t i=0;i<8;++i) {
        if(!((s[i]>='0' && s[i]<='9') || (s[i]>='A' && s[i]<='F'))) return false;
        if(s[i]!='0') nonzero=true;
    } return nonzero;
}
static bool begin(uint16_t seq,const char *session,char *out,size_t cap) {
    if(out && cap) out[0]=0;
    return out && cap>=APD_MCU_WIRE_BYTES && seq && valid_session(session);
}
static uint8_t crc(const char *s,size_t n) {
    uint8_t c=0;
    for(size_t i=0;i<n;++i) {
        c^=(uint8_t)s[i]; for(int k=0;k<8;++k) c=(uint8_t)((c<<1)^((c&128u)?7u:0u));
    } return c;
}
static bool wrap(const char *payload,char *out,size_t cap) {
    int n=snprintf(out,cap,"@%s*%02X\n",payload,(unsigned)crc(payload,strlen(payload)));
    if(n<0 || (size_t)n>=cap) {out[0]=0; return false;}
    return true;
}
static bool command(uint16_t seq,const char *session,const char *cmd,char *out,size_t cap) {
    if(!begin(seq,session,out,cap)) return false;
    char payload[64]; int n=snprintf(payload,sizeof(payload),"%u,%s,%s",(unsigned)seq,cmd,session);
    if(n<0 || (size_t)n>=sizeof(payload)) return false;
    return wrap(payload,out,cap);
}
bool apd_mcu_encode_hello(uint16_t seq,const char *session,char *out,size_t cap) {
    return command(seq,session,"HELLO",out,cap);
}
bool apd_mcu_encode_stop(uint16_t seq,const char *session,char *out,size_t cap) {
    return command(seq,session,"STOP",out,cap);
}
bool apd_mcu_encode_heartbeat(uint16_t seq,const char *session,char *out,size_t cap) {
    return command(seq,session,"H",out,cap);
}
bool apd_mcu_encode_report(uint16_t seq,const char *session,uint32_t frame,
                          const ws_report *r,char *out,size_t cap) {
    if(!begin(seq,session,out,cap) || !r || r->people_count>APD_MAX_PEOPLE ||
        r->observation<APD_UNKNOWN || r->observation>APD_STARTING) return false;
    static const char *names[]={"UNKNOWN","COMPLIANT","VIOLATION","NO_PERSON","CAMERA_LOST","MODEL_ERROR","STARTING"};
    bool fault=r->observation==APD_CAMERA_LOST || r->observation==APD_MODEL_ERROR || r->observation==APD_STARTING;
    bool no_target=fault || r->observation==APD_NO_PERSON || !r->indicator_track_id;
    uint64_t target=no_target?0:r->indicator_track_id;
    char states[4]="UUU"; bool alarm=false;
    if(target) {
        const ws_person_result *p=NULL;
        for(size_t i=0;i<r->people_count;++i) if(r->people[i].id==target) {
            if(p) return false;
            p=&r->people[i];
        }
        if(!p || p->identity_ambiguous) return false;
        bool negative=false;
        for(size_t i=0;i<WS_ITEMS;++i) {
            ws_item_state state=p->items[i].state; ws_source source=p->items[i].source;
            if(state==WS_UNKNOWN) states[i]='U';
            else if(state==WS_PRESENT && source==WS_FRESH) states[i]='P';
            else if(state==WS_PRESENT && source==WS_CACHED) states[i]='C';
            else if(state==WS_ABSENT && source==WS_FRESH) {states[i]='N'; negative=true;}
            else if(state==WS_ABSENT && source==WS_CACHED) states[i]='D';
            else return false;
            if((states[i]=='N' || states[i]=='D') && r->observation!=APD_VIOLATION) return false;
            if(r->observation==APD_COMPLIANT && states[i]!='P' && states[i]!='C') return false;
        }
        alarm=p->alarm_candidate && negative;
        if(alarm && r->observation!=APD_VIOLATION) return false;
    }
    char payload[APD_MCU_WIRE_BYTES];
    int n=snprintf(payload,sizeof(payload),"%u,DATA,%s,%" PRIu32 ",%s,%016" PRIX64 ",%s,%u",
        (unsigned)seq,session,frame,names[r->observation],target,states,alarm?1u:0u);
    if(n<0 || (size_t)n>=sizeof(payload)) return false;
    return wrap(payload,out,cap);
}
