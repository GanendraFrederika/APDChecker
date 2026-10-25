#include "receiver_core.h"
#include <string.h>
#include <stdio.h>

static uint8_t crc8(const char *s,size_t n) {
    uint8_t c=0; for(size_t i=0;i<n;++i) {
        c^=(uint8_t)s[i]; for(int k=0;k<8;++k) c=(uint8_t)((c<<1)^((c&128u)?7u:0u));
    } return c;
}
static void invalidate(mcu_receiver *r,mcu_status status) {
    r->handshake=false; r->has_sequence=false; r->has_frame=false;
    r->alarm_on=false; r->has_target=false; r->status=status;
    memset(r->items,0,sizeof(r->items)); r->session[0]=0; r->target[0]=0;
}
void mcu_init(mcu_receiver *r) {
    if (!r) return;
    memset(r,0,sizeof(*r)); r->status=MCU_STARTING;
}
static bool elapsed(uint32_t now,uint32_t then,uint32_t limit) {
    uint32_t d=now-then; return d>=limit || d>INT32_MAX;
}
void mcu_tick(mcu_receiver *r,uint32_t now) {
    if (!r) return;
    if (r->collecting && (elapsed(now,r->byte_ms,MCU_BYTE_TTL_MS) ||
                         elapsed(now,r->line_ms,MCU_BYTE_TTL_MS))) {
        r->collecting=false; r->used=0; invalidate(r,MCU_LINK_LOST);
    }
    if (r->has_frame && elapsed(now,r->data_ms,MCU_DATA_TTL_MS)) invalidate(r,MCU_LINK_LOST);
    if (r->alarm_on && elapsed(now,r->alarm_ms,MCU_ALARM_MS)) r->alarm_on=false;
}
static bool uint_value(const char *s,uint32_t max,uint32_t *v) {
    if (!*s || (s[0]=='0' && s[1])) return false;
    uint32_t n=0;
    for(;*s;++s) {
        if (*s<'0'||*s>'9') return false;
        uint32_t digit=(uint32_t)(*s-'0');
        if (n>max/10u || (n==max/10u && digit>max%10u)) return false;
        n=n*10u+digit;
    } *v=n; return true;
}
static int hex(char c) {
    if(c>='0' && c<='9') return c-'0';
    if(c>='A' && c<='F') return c-'A'+10;
    return -1;
}
static bool token(const char *s,size_t length,bool *nonzero) {
    if(strlen(s)!=length) return false;
    *nonzero=false;
    for(size_t i=0;i<length;++i) {if(hex(s[i])<0) return false; if(s[i]!='0') *nonzero=true;}
    return true;
}
static bool ack(uint16_t seq,const char *cmd,const char *state,char *reply,size_t cap) {
    char payload[64]; int n=snprintf(payload,sizeof(payload),"%u,ACK,%s,%s",(unsigned)seq,cmd,state);
    if(n<0 || (size_t)n>=sizeof(payload)) return false;
    int size=snprintf(reply,cap,"@%s*%02X\n",payload,(unsigned)crc8(payload,(size_t)n));
    return size>=0 && (size_t)size<cap;
}
static bool status_value(const char *s,mcu_status *status) {
    static const char *names[]={"STARTING","NO_PERSON","UNKNOWN","COMPLIANT","VIOLATION","CAMERA_LOST","MODEL_ERROR"};
    for(size_t i=0;i<7;++i) if(!strcmp(s,names[i])) {*status=(mcu_status)i; return true;}
    return false;
}
static bool parse(mcu_receiver *r,uint32_t now,char *reply,size_t cap) {
    char *star=strchr(r->line,'*');
    if(!star || strlen(star)!=3 || hex(star[1])<0 || hex(star[2])<0 ||
        crc8(r->line,(size_t)(star-r->line))!=(uint8_t)(hex(star[1])*16+hex(star[2]))) return false;
    *star=0;
    char *fields[9]; size_t count=1; fields[0]=r->line;
    for(char *s=r->line;*s;++s) if(*s==',') {
        if(count==9) return false;
        *s=0; fields[count++]=s+1;
    }
    for(size_t i=0;i<count;++i) if(!*fields[i]) return false;
    uint32_t seq;
    if(count<3 || !uint_value(fields[0],65535,&seq) || !seq) return false;
    bool nonzero=false;
    if(!strcmp(fields[1],"HELLO")) {
        if(count!=3 || !token(fields[2],8,&nonzero) || !nonzero) return false;
        /* HELLO always resets outputs/evidence; no power/alarm command. */
        invalidate(r,MCU_STARTING); memcpy(r->session,fields[2],9);
        r->handshake=true; r->has_sequence=true; r->sequence=(uint16_t)seq;
        return ack((uint16_t)seq,"HELLO","READY",reply,cap);
    }
    if(!r->handshake || strcmp(fields[2],r->session)) return false;
    uint16_t delta=(uint16_t)((uint16_t)seq-r->sequence);
    if(!r->has_sequence || !delta || delta>32767) return false;
    if(!strcmp(fields[1],"STOP")) {
        if(count!=3) return false;
        invalidate(r,MCU_STARTING); return ack((uint16_t)seq,"STOP","IDLE",reply,cap);
    }
    if(!strcmp(fields[1],"H")) {
        if(count!=3) return false;
        r->sequence=(uint16_t)seq;
        return ack((uint16_t)seq,"H",r->has_frame?"READY":"FAULT",reply,cap);
    }
    if(strcmp(fields[1],"DATA") || count!=8) return false;
    uint32_t frame;
    if(!uint_value(fields[3],UINT32_MAX,&frame)) return false;
    if(r->has_frame) {uint32_t gap=frame-r->frame_id; if(!gap || gap>INT32_MAX) return false;}
    mcu_status status;
    if(!status_value(fields[4],&status) || !token(fields[5],16,&nonzero) || strlen(fields[6])!=3 ||
       (strcmp(fields[7],"0") && strcmp(fields[7],"1"))) return false;
    mcu_item items[3]; bool fresh_negative=false, any_negative=false;
    for(size_t i=0;i<3;++i) {
        switch(fields[6][i]) {
        case 'U': items[i]=MCU_U; break;
        case 'P': items[i]=MCU_P; break;
        case 'C': items[i]=MCU_C; break;
        case 'N': items[i]=MCU_N; fresh_negative=true; break;
        case 'D': items[i]=MCU_D; break;
        default: return false;
        }
        if(items[i]==MCU_N || items[i]==MCU_D) any_negative=true;
    }
    if(any_negative && status!=MCU_VIOLATION) return false;
    bool alarm=fields[7][0]=='1';
    bool fault=status==MCU_STARTING || status==MCU_CAMERA_LOST || status==MCU_MODEL_ERROR;
    if((!nonzero || fault || status==MCU_NO_PERSON) && (strcmp(fields[6],"UUU") || alarm)) return false;
    if((fault || status==MCU_NO_PERSON) && nonzero) return false;
    if(status==MCU_COMPLIANT && nonzero) for(size_t i=0;i<3;++i) if(items[i]!=MCU_P && items[i]!=MCU_C) return false;
    /* Alarm route is conservative draft: explicit selected target, fresh N.
     * Never aggregate lamps/alarms across different workers on the receiver. */
    if(alarm && (!nonzero || status!=MCU_VIOLATION || !fresh_negative)) return false;
    if(strcmp(r->target,fields[5])) r->alarm_on=false;
    if(!alarm || fault) r->alarm_on=false;
    else if(!r->has_alarm || elapsed(now,r->alarm_ms,MCU_ALARM_COOLDOWN_MS)) {
        r->alarm_on=true; r->has_alarm=true; r->alarm_ms=now;
    }
    r->sequence=(uint16_t)seq; r->has_frame=true; r->frame_id=frame; r->data_ms=now;
    r->status=status; r->has_target=nonzero; memcpy(r->target,fields[5],17);
    memcpy(r->items,items,sizeof(items));
    return ack((uint16_t)seq,"DATA",fault?"FAULT":"READY",reply,cap);
}
bool mcu_feed(mcu_receiver *r,char byte,uint32_t now,char *reply,size_t cap) {
    if(reply && cap) reply[0]=0;
    if(!r || !reply || cap<MCU_LINE_BYTES) {
        if(r) {r->collecting=false; r->used=0; invalidate(r,MCU_MODEL_ERROR);}
        return false;
    }
    mcu_tick(r,now);
    if(byte=='@') {
        if(r->collecting) invalidate(r,MCU_LINK_LOST);
        r->collecting=true; r->used=0; r->byte_ms=now; r->line_ms=now; return false;
    }
    if(!r->collecting) return false; /* Ignore naked legacy commands. */
    r->byte_ms=now;
    if(byte=='\n') {
        r->collecting=false;
        if(r->used && r->line[r->used-1]=='\r') --r->used;
        r->line[r->used]=0;
        bool ok=parse(r,now,reply,cap); r->used=0;
        if(!ok) {invalidate(r,MCU_LINK_LOST); reply[0]=0;}
        return ok;
    }
    if(r->used>=MCU_LINE_BYTES-1 || ((unsigned char)byte<32 && byte!='\r') || (unsigned char)byte>126) {
        r->collecting=false; r->used=0; invalidate(r,MCU_LINK_LOST); return false;
    }
    r->line[r->used++]=byte; return false;
}
bool mcu_fault(const mcu_receiver *r) {
    return !r || !r->has_frame || r->status==MCU_STARTING || r->status==MCU_CAMERA_LOST ||
        r->status==MCU_MODEL_ERROR || r->status==MCU_LINK_LOST;
}
bool mcu_indicator(const mcu_receiver *r,size_t item,uint32_t now) {
    if(!r || item>=3 || !r->has_target || mcu_fault(r)) return false;
    if(r->items[item]==MCU_P || r->items[item]==MCU_C) return true;
    return r->items[item]==MCU_U && (now/500u)%2u==0;
}
