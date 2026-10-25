/* Portable decoder candidate, HOST tests only. NOT RKNN/camera integration.
 * ONLY exported YOLOv5 post-sigmoid INT8 affine, three NCHW anchor heads,
 * seven classes. Not YOLOv8, logits, NHWC or NC1HWC2. Runtime adapter must
 * validate actual tensor attributes AND model/export manifest before use.
 * Caller-owned workspace, no heap. Overflow fails, never silently top-K.
 */
#ifndef APD_GRID_DECODER_H
#define APD_GRID_DECODER_H
#include "backend_frame.h"
#define APD_GRID_HEADS 3
#define APD_GRID_ANCHORS 3
#define APD_GRID_CHANNELS (APD_GRID_ANCHORS * (5 + APD_WORKSHOP_CLASSES))
#define APD_GRID_MAX_CANDIDATES 256
#define APD_GRID_POSTSIGMOID_I8_NCHW_7 1u

typedef struct {
    const int8_t *data;
    size_t byte_count, row_stride, channel_stride;
    uint32_t grid_width, grid_height, pixel_stride;
    int32_t zero_point;
    float scale;
    float anchors[APD_GRID_ANCHORS][2]; /* from this model export, not COCO defaults */
} apd_grid_head;
typedef struct {
    uint32_t contract, input_width, input_height;
    float score_threshold, nms_iou;
    apd_grid_head heads[APD_GRID_HEADS];
} apd_grid_input;
typedef struct {
    apd_box box;
    uint8_t class_id;
    bool suppressed;
} apd_grid_candidate;
typedef struct {
    apd_grid_candidate candidates[APD_GRID_MAX_CANDIDATES];
    uint16_t order[APD_GRID_MAX_CANDIDATES];
    size_t count;
} apd_grid_workspace;
/* Deterministic argmax single-label per anchor; ties lower class ID. Scores
 * descending, ties head/anchor/row/column order. Class-aware NMS on clipped
 * boxes; opposing labels NEVER suppress each other. This decoding policy
 * must match evaluation/export, not silently changed at deployment.
 * Person visibility always UNKNOWN; decoder cannot establish observability.
 * Quantized probabilities allow half-scale rounding error then clamp 0..1.
 * Any bad contract/value/capacity returns false, clears workspace count and
 * ALL caller output (capacity <= APD_MAX_RAW_DETECTIONS) / sets count=0.
 * Input/workspace/output buffers must NOT alias. A false return MUST map to
 * MODEL_ERROR, not NO_PERSON. Workspaces are not a shared/global singleton.
 */
bool apd_grid_decode(const apd_grid_input *input, apd_grid_workspace *workspace,
    apd_raw_detection *output, size_t capacity, size_t *count);
#endif
