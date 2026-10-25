/* Host unit test. Does not initialize camera, NPU, USB, or GPIO. */
#include "apd_core.h"
#include "session.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    apd_box people[] = {{0, 0, 100, 200, 0.9f}, {150, 0, 250, 200, 0.9f}};
    apd_equipment gear[] = {
        {{10, 0, 40, 30, 0.9f}, APD_HELMET, false},
        {{10, 30, 40, 60, 0.9f}, APD_MASK, false}
    };
    apd_assessment result;
    assert(apd_assess(people, 2, gear, 2, APD_HELMET | APD_MASK, 0.4f, &result));
    assert(result.observation == APD_UNKNOWN);
    assert(result.people[0].state == APD_COMPLIANT);
    assert(result.people[1].state == APD_UNKNOWN);
    gear[0].negative = true;
    assert(apd_assess(people, 2, gear, 2, APD_HELMET | APD_MASK, 0.4f, &result));
    assert(result.observation == APD_VIOLATION);
    assert(!apd_assess(people, APD_MAX_PEOPLE + 1, gear, 2, APD_HELMET, 0.4f, &result));
    assert(result.observation == APD_MODEL_ERROR);
    apd_debouncer d;
    apd_timing timing = {1500, 3000, 2000, 3};
    assert(apd_debouncer_init(&d, timing));
    assert(apd_debouncer_update(&d, APD_VIOLATION, 0));
    assert(!d.alarm_indication);
    assert(apd_debouncer_update(&d, APD_VIOLATION, 750));
    assert(apd_debouncer_update(&d, APD_VIOLATION, 1500));
    assert(d.alarm_indication);
    assert(apd_debouncer_update(&d, APD_UNKNOWN, 1750));
    assert(d.alarm_indication);
    assert(apd_debouncer_update(&d, APD_CAMERA_LOST, 2000));
    assert(!d.alarm_indication);
    assert(!apd_debouncer_update(&d, APD_VIOLATION, 2000));
    assert(apd_crc8((const uint8_t *)"123456789", 9) == 0xf4);
    /* Uint32 monotonic clock wrap. */
    assert(apd_debouncer_init(&d, timing));
    assert(apd_debouncer_update(&d, APD_VIOLATION, UINT32_MAX - 1000));
    assert(apd_debouncer_update(&d, APD_VIOLATION, UINT32_MAX - 250));
    assert(apd_debouncer_update(&d, APD_VIOLATION, 499));
    assert(d.alarm_indication);
    apd_session session;
    assert(apd_session_init(&session, APD_HELMET | APD_MASK, 0.4f, timing, 2000, 0));
    apd_inference_frame frame = {0};
    frame.frame_id = 1; frame.captured_monotonic_ms = 0;
    frame.people_count = 1; frame.people[0] = people[0];
    frame.equipment_count = 1; frame.equipment[0] = gear[0];
    assert(apd_session_accept(&session, &frame, 0));
    assert(!apd_session_accept(&session, &frame, 750));
    assert(session.debounce.samples == 1);
    frame.frame_id = 2; frame.captured_monotonic_ms = 750;
    assert(apd_session_accept(&session, &frame, 750));
    frame.frame_id = 3; frame.captured_monotonic_ms = 1500;
    assert(apd_session_accept(&session, &frame, 1500));
    assert(session.debounce.alarm_indication);
    assert(!apd_session_outputs_enabled(&session));
    apd_session_tick(&session, 3500);
    assert(session.assessment.observation == APD_CAMERA_LOST);
    assert(!session.debounce.alarm_indication);
    assert(!apd_session_outputs_enabled(&session));
    puts("APD native core tests passed; NO HARDWARE accessed");
    return 0;
}
