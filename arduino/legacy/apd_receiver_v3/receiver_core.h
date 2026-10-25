/* APD3 portable receiver candidate. HOST tests != commissioned hardware.
 * No GPIO/serial dependencies, no heap. Old v1.9 must NEVER receive APD3.
 */
#ifndef APD_RECEIVER_CORE_H
#define APD_RECEIVER_CORE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define MCU_LINE_BYTES 128
#define MCU_DATA_TTL_MS 1500u
#define MCU_BYTE_TTL_MS 250u
#define MCU_ALARM_MS 750u
#define MCU_ALARM_COOLDOWN_MS 10000u
typedef enum { MCU_U, MCU_P, MCU_C, MCU_N, MCU_D } mcu_item;
typedef enum { MCU_STARTING, MCU_NO_PERSON, MCU_UNKNOWN, MCU_COMPLIANT,
    MCU_VIOLATION, MCU_CAMERA_LOST, MCU_MODEL_ERROR, MCU_LINK_LOST } mcu_status;
typedef struct {
    char line[MCU_LINE_BYTES]; size_t used; uint32_t byte_ms, line_ms;
    bool collecting, handshake, has_sequence, has_frame, alarm_on, has_alarm;
    uint16_t sequence; uint32_t frame_id, data_ms, alarm_ms;
    char session[9], target[17]; mcu_status status; mcu_item items[3];
    bool has_target;
} mcu_receiver;
void mcu_init(mcu_receiver *r);
/* reply cleared on no complete valid frame; errors discard all evidence AND
 * session. CRC detects accidents only, not authentication or adversarial replay. */
bool mcu_feed(mcu_receiver *r, char byte, uint32_t now_ms,
              char *reply, size_t reply_capacity);
void mcu_tick(mcu_receiver *r, uint32_t now_ms);
/* Draft display: P/C steady, N/D off, U slow blink only if a target exists.
 * Fault indication is separate. Physical display/alarm policy NOT commissioned. */
bool mcu_indicator(const mcu_receiver *r, size_t item, uint32_t now_ms);
bool mcu_fault(const mcu_receiver *r);
#endif
