/* Pure HOST-tested integration building block, NOT a camera/RKNN driver.
 * Boxes are POST-NMS, model-input pixel coordinates. Use the ACTUAL integer
 * resize/padding applied to this frame, never an assumed ideal scale.
 * Full-frame rotation + recorded resize/padding only: no crop, mirror or
 * nonlinear lens-distortion support.
 * Visibility is supplied independently, never derived from box containment.
 */
#ifndef APD_BACKEND_FRAME_H
#define APD_BACKEND_FRAME_H
#include "workshop_tracker.h"
#define APD_WORKSHOP_CLASSES 7
#define APD_MAX_RAW_DETECTIONS (APD_MAX_PEOPLE + APD_MAX_EQUIPMENT)
typedef enum { APD_LABEL_PERSON, APD_LABEL_VEST, APD_LABEL_NO_VEST,
    APD_LABEL_SHOES, APD_LABEL_NO_SHOES, APD_LABEL_HELMET,
    APD_LABEL_NO_HELMET } apd_workshop_label;
typedef struct {
    uint32_t camera_width, camera_height, input_width, input_height;
    uint32_t resized_width, resized_height, pad_left, pad_top;
    uint16_t clockwise_rotation;
} apd_frame_transform;
typedef struct {
    apd_box box;
    size_t class_id;
    ws_visibility visibility[WS_ITEMS]; /* person only; other labels ignored */
} apd_raw_detection;
typedef enum { APD_MAP_INVALID, APD_MAP_PADDING_ONLY, APD_MAP_BOX } apd_map_status;
bool apd_transform_valid(const apd_frame_transform *transform);
/* Tracker coordinates: unpadded full-frame view AFTER clockwise rotation.
 * This view must be upright; the tracker uses head/torso/feet vertical zones. */
apd_map_status apd_unletterbox_box(const apd_frame_transform *transform,
                                   apd_box input, apd_box *view_box);
/* Raw sensor coordinates for overlays ONLY. Never feed a sideways/upside-down
 * raw frame to the tracker, whose body zones assume an upright view. */
apd_map_status apd_inverse_box(const apd_frame_transform *transform,
                               apd_box input, apd_box *camera_box);
/* Label IDs are an explicit permutation of the seven required classes; no
 * aliases, implicit COCO defaults, mask-to-vest mapping or missing negatives.
 * Do not call before validating the model manifest/hash/tensor contract.
 * Frame boxes are in the UPRIGHT rotated view, NOT raw sensor orientation.
 * Builder resets view fields to zero/stable for fixed-view compatibility.
 * Moving-camera backend MUST then stamp saved EXPOSURE-time camera_view_epoch
 * and camera_view_unstable before ws_update. Do not use current servo state on
 * a buffered frame, and invalidate the tracker/report BEFORE starting motion.
 * Returns false and clears all evidence to MODEL_ERROR on malformed input or
 * overflow. This is not a runtime/model/accuracy acceptance check.
 */
bool apd_build_workshop_frame(const apd_frame_transform *transform,
    const apd_workshop_label *labels, size_t label_count,
    const apd_raw_detection *detections, size_t detection_count,
    uint64_t frame_id, uint32_t captured_ms, uint32_t received_ms,
    ws_frame *frame);
#endif
