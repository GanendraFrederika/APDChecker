"""Generate HOST assertions for REAL candidate C receiver; no serial/board IO.
Python codec bytes include CRC; malformed corpus and temporal sequences assert
session invalidation, freshness/timeout, draft lamps/alarm/cooldown. No accuracy
or physical commissioning claims. Naked bytes test legacy commands are ignored.
"""
import json
from pathlib import Path
from apd_runtime.mcu_protocol import hello, data, heartbeat, stop
from apd_runtime.protocol import encode_frame


def generate_test(path):
    lines=['#include "receiver_core.h"','#include <assert.h>','#include <string.h>',
           '#include <stdio.h>','static mcu_receiver r; static char reply[MCU_LINE_BYTES];',
           'static int send(const char *bytes,uint32_t now) {int ok=0;',
           'for(size_t i=0;i<strlen(bytes);++i) if(mcu_feed(&r,bytes[i],now,reply,sizeof(reply))) ++ok;',
           'return ok;}','int main(void) {']
    checks=0
    def raw(blob,now,accepted):
        nonlocal checks
        text=blob.decode('ascii') if isinstance(blob,bytes) else blob
        lines.append(f'assert(send({json.dumps(text)},{now}u)=={int(accepted)});');checks+=1
    def reset(): lines.append('mcu_init(&r);')
    def connect(): raw(hello(1,'1234ABCD'),0,True)
    reset(); raw('1ARr0S',0,False)
    lines+=['assert(!r.handshake && !r.alarm_on && mcu_fault(&r));']
    connect(); lines+=['assert(r.handshake && mcu_fault(&r));','assert(strstr(reply,",ACK,HELLO,READY*")!=NULL);']
    raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0,True)
    lines+=['assert(!mcu_fault(&r));','for(size_t k=0;k<3;++k) assert(mcu_indicator(&r,k,0));']
    raw(data(3,'1234ABCD',2,'UNKNOWN',1,'CUU'),300,True)
    lines+=['assert(mcu_indicator(&r,0,500));','assert(!mcu_indicator(&r,1,500));','assert(mcu_indicator(&r,1,1000));']
    # Heartbeat advances serial seq but NOT data timestamp or frame id.
    raw(heartbeat(4,'1234ABCD'),900,True)
    lines+=['assert(r.data_ms==300);','mcu_tick(&r,1799); assert(r.has_frame);',
            'mcu_tick(&r,1800); assert(mcu_fault(&r) && !r.has_frame && !r.handshake);',
            'for(size_t k=0;k<3;++k) assert(!mcu_indicator(&r,k,1800));']
    raw(data(5,'1234ABCD',3,'COMPLIANT',1,'PPP'),1801,False)
    reset(); connect()
    raw(data(2,'1234ABCD',1,'VIOLATION',1,'NPP',True),0,True)
    lines+=['assert(r.alarm_on);','mcu_tick(&r,749); assert(r.alarm_on);','mcu_tick(&r,750); assert(!r.alarm_on);']
    raw(data(3,'1234ABCD',2,'VIOLATION',1,'NPP',True),800,True)
    lines+=['assert(!r.alarm_on);']
    # Cooldown while continuously fresh frame reports arrive.
    for frame in range(3,14): raw(data(frame+1,'1234ABCD',frame,'VIOLATION',1,'NPP',True),(frame-1)*800,True)
    raw(data(15,'1234ABCD',14,'VIOLATION',1,'NPP',True),10000,True)
    lines+=['assert(r.alarm_on);']
    raw(data(16,'1234ABCD',15,'UNKNOWN',1,'UPP'),10100,True)
    lines+=['assert(!r.alarm_on);']
    raw(stop(17,'1234ABCD'),10200,True)
    lines+=['assert(!r.handshake && !r.has_frame && !r.alarm_on);']
    # Serial and frame counters may wrap only forward within half-range.
    reset(); raw(hello(65535,'1234ABCD'),0,True)
    raw(data(1,'1234ABCD',0xffffffff,'COMPLIANT',1,'PPP'),0,True)
    raw(data(2,'1234ABCD',0,'COMPLIANT',1,'CCC'),300,True)
    lines+=['assert(r.frame_id==0 && !mcu_fault(&r));']
    # uint32 millis wrap doesn't immediately expire fresh evidence.
    reset(); raw(hello(1,'1234ABCD'),0xffffff00,True)
    raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0xffffff00,True)
    lines+=['mcu_tick(&r,100); assert(r.has_frame);','mcu_tick(&r,1244); assert(!r.handshake && mcu_fault(&r));']
    # Fault frames clear lamps/alarm while accepted for explicit fault ACK.
    for status in ('STARTING','CAMERA_LOST','MODEL_ERROR'):
        reset(); connect();raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0,True)
        raw(data(3,'1234ABCD',2,status,0,'UUU'),300,True)
        lines+=['assert(mcu_fault(&r) && !r.has_target && !r.alarm_on);','assert(strstr(reply,",ACK,DATA,FAULT*")!=NULL);']
    # Malformed frame after valid positive evidence invalidates session.
    malformed=[b'@2,DATA*00\n', encode_frame(3,'DATA','1234ABCD','1','COMPLIANT','0000000000000001','PPP','0'),
               data(2,'1234ABCD',2,'COMPLIANT',1,'PPP'), # duplicate serial sequence
               data(3,'DEADBEEF',2,'COMPLIANT',1,'PPP'),
               data(3,'1234ABCD',0,'COMPLIANT',1,'PPP'), # backwards frame ID
               encode_frame(3,'DATA','1234ABCD','2','UNKNOWN','0000000000000001','NPP','0'),
               encode_frame(3,'DATA','1234ABCD','2','BAD','0000000000000001','PPP','0'),
               encode_frame(3,'DATA','1234ABCD','2','CAMERA_LOST','0000000000000001','PPP','0'),
               encode_frame(3,'DATA','1234ABCD','2','VIOLATION','0000000000000000','UUU','1'),
               encode_frame(3,'DATA','1234ABCD','2','VIOLATION','0000000000000001','CCC','1'),
               encode_frame(3,'DATA','1234ABCD','4294967296','COMPLIANT','0000000000000001','PPP','0'),
               encode_frame(3,'DATA','1234ABCD','02','COMPLIANT','0000000000000001','PPP','0'),
               b'@'+b'X'*128+b'\n',b'@3,HELLO,1234ABCD*00\n']
    # Single-byte corruption at every byte of a valid DATA, except framing:
    # framing corruption is handled by partial frame/TTL, not immediate parse.
    valid=data(3,'1234ABCD',2,'COMPLIANT',1,'PPP')
    for i in range(1,len(valid)-1):
        corrupted=bytearray(valid);corrupted[i]=ord('Z') if corrupted[i]!=ord('Z') else ord('Y')
        malformed.append(bytes(corrupted))
    for blob in malformed:
        reset(); connect(); raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0,True)
        raw(blob,300,False)
        lines+=['assert(!r.handshake && mcu_fault(&r) && !r.has_frame && !r.alarm_on);',
                'for(size_t k=0;k<3;++k) assert(!mcu_indicator(&r,k,300));']
    reset();connect();raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0,True)
    raw('@3,DATA',300,False)
    lines+=['mcu_tick(&r,549); assert(r.has_frame);','mcu_tick(&r,550); assert(!r.handshake && !r.collecting && mcu_fault(&r));']
    # Differential byte-by-byte corruption and flood with embedded delimiters.
    # Prefix HELLO after every case recovers by invalidating any partial parse.
    reset();connect();raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0,True)
    raw('@'+'X'*20+'\r'+'X'*5+'\n',300,False)
    lines+=['assert(mcu_fault(&r) && !r.handshake);']
    # Whole-line timeout stops slow drip from making arbitrarily delayed DATA.
    reset();connect();raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0,True)
    raw('@',100,False)
    raw('3',200,False); raw(',',300,False)
    lines+=['mcu_tick(&r,349); assert(r.collecting);','mcu_tick(&r,350); assert(!r.collecting && !r.handshake);']
    # Target change must stop an existing pulse, not transfer it to next worker.
    reset();connect();raw(data(2,'1234ABCD',1,'VIOLATION',1,'NPP',True),0,True)
    lines+=['assert(r.alarm_on);']
    raw(data(3,'1234ABCD',2,'VIOLATION',2,'NPP',True),300,True)
    lines+=['assert(!r.alarm_on);']
    # A repeated HELLO always clears even a currently active alarm.
    reset();connect();raw(data(2,'1234ABCD',1,'VIOLATION',1,'NPP',True),0,True)
    raw(hello(3,'DEADBEEF'),300,True)
    lines+=['assert(!r.alarm_on && !r.has_frame && r.handshake);']
    # Malformed/unterminated nested start drops old evidence immediately.
    reset();connect();raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0,True)
    raw('@3,DATA@',300,False)
    lines+=['assert(!r.has_frame && mcu_fault(&r));']
    # Null/small reply buffers cannot preserve prior evidence.
    reset();connect();raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP'),0,True)
    lines+=['assert(!mcu_feed(&r,\'@\',300,NULL,0));',
            'assert(!r.has_frame && mcu_fault(&r));']
    # CRLF accepted, junk/nonframed bytes cannot update data freshness.
    reset();connect();raw(data(2,'1234ABCD',1,'COMPLIANT',1,'PPP').replace(b'\n',b'\r\n'),0,True)
    raw('HELLO1R',100,False);lines+=['assert(r.data_ms==0);']
    lines+=['mcu_tick(&r,1500); assert(mcu_fault(&r) && !r.handshake);',
            'printf("MCU C receiver HOST PASS: '+str(checks)+' byte streams; sizeof=%zu; NO UART/GPIO\\n",sizeof(r));',
            'return 0;}']
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf8')
    return checks
