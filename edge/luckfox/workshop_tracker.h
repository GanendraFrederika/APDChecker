/* Bounded C99 workshop reference. No camera/NPU/serial/GPIO; NOT deployed.
 * Visibility must be supplied by an independently validated backend, never
 * inferred from a missing detection. IoU track IDs are temporary, not identity.
 * One tracker instance owns all state. No heap; timestamps CLOCK_MONOTONIC ms.
 */
#ifndef APD_WORKSHOP_TRACKER_H
#define APD_WORKSHOP_TRACKER_H
#include "apd_core.h"
#define WS_ITEMS 3
#define WS_VEST 0
#define WS_SHOES 1
#define WS_HELMET 2

typedef enum { WS_UNKNOWN, WS_PRESENT, WS_ABSENT, WS_CONFLICT } ws_item_state;
typedef enum { WS_VIS_UNKNOWN, WS_OBSERVABLE, WS_NOT_VISIBLE } ws_visibility;
typedef enum { WS_NONE, WS_FRESH, WS_CACHED } ws_source;
typedef struct {
    ws_item_state state, candidate;
    uint32_t observed_ms, since_ms, previous_ms;
    uint16_t samples;
    float confidence;
    bool has_observed, has_candidate;
} ws_memory;
typedef struct {
    uint64_t id;
    apd_box box;
    uint32_t last_seen_ms;
    ws_memory items[WS_ITEMS];
} ws_track;
typedef struct {
    float confidence, match_iou, overlap_fraction;
    uint32_t present_ms, absent_ms, evidence_ttl_ms, lost_ttl_ms;
    uint32_t max_gap_ms, max_frame_age_ms;
    uint16_t present_samples, absent_samples;
} ws_settings;
typedef struct {
    uint64_t frame_id;
    uint32_t captured_ms, received_ms;
    size_t people_count, equipment_count;
    apd_box people[APD_MAX_PEOPLE];
    apd_equipment equipment[APD_MAX_EQUIPMENT];
    /* Current INPUT detection index, kept aligned when confidence-filtering. */
    ws_visibility visibility[APD_MAX_PEOPLE][WS_ITEMS];
    apd_observation fault; /* APD_UNKNOWN means no backend fault. */
    uint64_t selected_track_id; /* 0 = automatic only for a single person */
    /* EXPOSURE-time view metadata, never current inference-time servo position.
     * Zero/stable is legacy fixed-view compatibility, NOT a moving default. */
    uint64_t camera_view_epoch;
    bool camera_view_unstable; /* movement OR settle OR unknown pose */
} ws_frame;
typedef struct {
    ws_item_state state, observation;
    ws_source source;
    ws_visibility visibility;
    uint32_t observed_ms;
    bool has_observed;
    float confidence;
} ws_item_result;
typedef struct {
    uint64_t id;
    apd_box box;
    ws_item_result items[WS_ITEMS];
    apd_observation observation;
    bool identity_ambiguous, alarm_candidate;
} ws_person_result;
typedef struct {
    apd_observation observation;
    size_t people_count, retained_tracks, unassigned_equipment;
    ws_person_result people[APD_MAX_PEOPLE];
    uint64_t indicator_track_id;
    ws_item_state indicators[WS_ITEMS];
    bool alarm_candidate;
} ws_report;
typedef struct {
    ws_settings settings;
    ws_track tracks[APD_MAX_PEOPLE];
    size_t count;
    uint64_t next_id, previous_frame_id, camera_view_epoch;
    uint32_t previous_ms;
    bool has_previous;
} ws_tracker;
ws_settings ws_defaults(void);
bool ws_init(ws_tracker *tracker, ws_settings settings);
/* False = invalid input/frame freshness; flush evidence, report MODEL_ERROR.
 * Backend faults are accepted reports but always flush evidence. */
bool ws_update(ws_tracker *tracker, const ws_frame *frame, ws_report *report);
/* BEFORE motion/view changes: flush evidence and replace the held report even
 * between inference frames. Strictly newer epoch; keep IDs/timestamps monotonic.
 * Reject old queued views; caller must stamp exposure-time metadata on frames.
 * This has no GPIO/servo effects. False clears report to MODEL_ERROR. */
bool ws_invalidate_camera_view(ws_tracker *tracker, uint64_t epoch, ws_report *report);
/* Must be called between inference frames: stale cached reports cannot be held
 * forever. A stale report is cleared and CAMERA_LOST; no hardware actuation. */
void ws_tick(ws_tracker *tracker, uint32_t now_ms, ws_report *report);
bool ws_outputs_enabled(void);
#endif
