/* APD3 byte encoder ONLY, no UART/GPIO/open/actuation. NOT for legacy v1.9.
 * Caller MUST use fresh tracker reports and a verified APD3 receiver; transport
 * must not regenerate DATA from cached reports. CRC != authentication.
 */
#ifndef APD_MCU_FRAME_H
#define APD_MCU_FRAME_H
#include "workshop_tracker.h"
#define APD_MCU_WIRE_BYTES 128
bool apd_mcu_encode_hello(uint16_t sequence,const char *session,char *out,size_t cap);
bool apd_mcu_encode_stop(uint16_t sequence,const char *session,char *out,size_t cap);
bool apd_mcu_encode_heartbeat(uint16_t sequence,const char *session,char *out,size_t cap);
/* frame_id is a new uint32 transport capture ID (wrap permitted), NOT number of
 * times the cached report was read. Do not resend identical frame IDs.
 * Emits item/source symbols for ONE selected person; no global alarm/lamp OR.
 * Fault/no-target -> UUU/no alarm. False clears output buffer, no send allowed.
 * Alarm duration/cooldown/display/selection remain uncommissioned draft policy.
 */
bool apd_mcu_encode_report(uint16_t sequence,const char *session,uint32_t frame_id,
                          const ws_report *report,char *out,size_t cap);
#endif
