/* Offline-buildable coordinator for a future RK-MPI/RKNN application.
 * This development version NEVER enables hardware outputs.
 */
#ifndef APD_SESSION_H
#define APD_SESSION_H
#include "backend_contract.h"

typedef struct {
    apd_debouncer debounce;
    apd_assessment assessment;
    uint8_t required;
    float min_confidence;
    uint32_t stale_ms, started_ms, last_capture_ms;
    uint64_t last_frame_id;
    bool has_frame;
} apd_session;

bool apd_session_init(apd_session *session, uint8_t required, float min_confidence,
                      apd_timing timing, uint32_t stale_ms, uint32_t now_ms);
bool apd_session_accept(apd_session *session, const apd_inference_frame *frame,
                        uint32_t now_ms);
void apd_session_tick(apd_session *session, uint32_t now_ms);
void apd_session_fault(apd_session *session, apd_observation fault);
bool apd_session_outputs_enabled(const apd_session *session);
#endif
