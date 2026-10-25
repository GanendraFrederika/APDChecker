/* Integration contract ONLY. No stub fabricates working camera or inference.
 * Future RK-MPI/RKNN adapter must supply person + PPE boxes in the SAME
 * UPRIGHT full-frame view coordinates, after undoing letterbox padding/scaling.
 * Keep the calibrated viewing rotation: workshop body zones assume upright
 * people. Raw sensor inverse rotation is for overlays only. Confidence and
 * labels are post-NMS. Invalid/overflow detections must report MODEL_ERROR.
 */
#ifndef APD_BACKEND_CONTRACT_H
#define APD_BACKEND_CONTRACT_H
#include "apd_core.h"

typedef struct {
    /* Identity of one newly inferred camera frame. Use a strictly increasing
     * uint64 ID; time is from CLOCK_MONOTONIC, not unsynchronized board RTC. */
    uint64_t frame_id;
    uint32_t captured_monotonic_ms;
    apd_box people[APD_MAX_PEOPLE];
    size_t people_count;
    apd_equipment equipment[APD_MAX_EQUIPMENT];
    size_t equipment_count;
} apd_inference_frame;

typedef enum { APD_BACKEND_FRAME, APD_BACKEND_NO_NEW_FRAME,
               APD_BACKEND_CAMERA_ERROR, APD_BACKEND_MODEL_ERROR } apd_backend_status;

typedef struct {
    void *context;
    /* No hidden downloads, no automatic camera start, no serial/relay access.
     * Caller owns lifetime. Return NO_NEW_FRAME rather than repeat cached data.
     * Implementation must enforce timeout and release every RK-MPI media buffer.
     * Crop/rotation and label manifest must be fixed before init succeeds. */
    bool (*init)(void *context, const char *model_manifest_path);
    apd_backend_status (*next)(void *context, uint32_t timeout_ms,
                               apd_inference_frame *frame);
    void (*close)(void *context);
} apd_backend;
#endif
