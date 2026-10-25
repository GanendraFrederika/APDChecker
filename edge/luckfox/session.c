#include "session.h"
#include <math.h>
#include <string.h>

bool apd_session_init(apd_session *s, uint8_t required, float confidence,
                      apd_timing timing, uint32_t stale_ms, uint32_t now) {
    if (!s) return false;
    memset(s, 0, sizeof(*s));
    s->assessment.observation = APD_STARTING;
    if (!required || (required & ~APD_ALL_PPE) || !isfinite(confidence) ||
        confidence <= 0 || confidence > 1 || !stale_ms || stale_ms > INT32_MAX ||
        !apd_debouncer_init(&s->debounce, timing)) return false;
    s->required = required; s->min_confidence = confidence;
    s->stale_ms = stale_ms; s->started_ms = now;
    return true;
}

void apd_session_fault(apd_session *s, apd_observation fault) {
    if (!s) return;
    if (fault != APD_CAMERA_LOST && fault != APD_MODEL_ERROR && fault != APD_STARTING)
        fault = APD_MODEL_ERROR;
    memset(&s->assessment, 0, sizeof(s->assessment));
    s->assessment.observation = fault;
    apd_debouncer_fault(&s->debounce);
}

void apd_session_tick(apd_session *s, uint32_t now) {
    if (!s) return;
    if (!s->stale_ms) { apd_session_fault(s, APD_MODEL_ERROR); return; }
    uint32_t age = now - (s->has_frame ? s->last_capture_ms : s->started_ms);
    if (age > INT32_MAX) { apd_session_fault(s, APD_MODEL_ERROR); return; }
    if (age >= s->stale_ms) apd_session_fault(s, APD_CAMERA_LOST);
}

bool apd_session_accept(apd_session *s, const apd_inference_frame *frame, uint32_t now) {
    if (!s || !frame) return false;
    if (!s->required || !s->stale_ms) { apd_session_fault(s, APD_MODEL_ERROR); return false; }
    uint32_t age = now - frame->captured_monotonic_ms;
    if (age > INT32_MAX) { apd_session_fault(s, APD_MODEL_ERROR); return false; }
    if (age >= s->stale_ms) { apd_session_fault(s, APD_CAMERA_LOST); return false; }
    if (s->has_frame && frame->frame_id <= s->last_frame_id) {
        if (frame->frame_id < s->last_frame_id) apd_session_fault(s, APD_MODEL_ERROR);
        else apd_session_tick(s, now); /* Same frame cannot increase sample count. */
        return false;
    }
    if (!apd_assess(frame->people, frame->people_count, frame->equipment,
                    frame->equipment_count, s->required, s->min_confidence, &s->assessment)) {
        apd_session_fault(s, APD_MODEL_ERROR); return false;
    }
    if (!apd_debouncer_update(&s->debounce, s->assessment.observation,
                              frame->captured_monotonic_ms)) {
        apd_session_fault(s, APD_MODEL_ERROR); return false;
    }
    s->has_frame = true; s->last_frame_id = frame->frame_id;
    s->last_capture_ms = frame->captured_monotonic_ms;
    return true;
}

bool apd_session_outputs_enabled(const apd_session *session) {
    (void)session;
    return false; /* Deliberate compile-time development lock, not a GPIO driver. */
}
