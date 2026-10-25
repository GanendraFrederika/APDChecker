/* RKNN engine CANDIDATE: HOST mocked tests only, never deployed.
 * Include rknn_api.h from a separately licensed and verified matching SDK.
 * No camera/media, UART/GPIO, downloads, or actuator access in this layer.
 * Packed native NCHW INT8 heads ONLY. Unsupported native packing is an error.
 */
#ifndef APD_RKNN_ENGINE_H
#define APD_RKNN_ENGINE_H
#include "grid_decoder.h"
#include <rknn_api.h>
#define APD_RKNN_MAX_IO_BYTES (4u * 1024u * 1024u)
typedef enum { APD_RKNN_NEW, APD_RKNN_READY, APD_RKNN_FAULT,
               APD_RKNN_CLOSED } apd_rknn_state;
typedef struct {
    /* Caller must authenticate model bytes/hash, export manifest, seven labels,
     * normalization/RGB/order/anchors and SDK ABI BEFORE setting this gate.
     * This boolean is NOT a validator, release approval, or security boundary. */
    bool model_and_sdk_verified;
    uint32_t contract, width, height, max_age_ms, max_io_bytes;
    float score_threshold, nms_iou;
    char api_version[256], driver_version[256]; /* exact queried strings */
    struct { uint32_t stride; int32_t zp; float scale;
             float anchors[APD_GRID_ANCHORS][2]; } head[APD_GRID_HEADS];
} apd_rknn_contract;
typedef struct {
    apd_rknn_state state;
    rknn_context ctx;
    rknn_tensor_mem *mem[1 + APD_GRID_HEADS];
    rknn_tensor_attr input, output[APD_GRID_HEADS];
    apd_rknn_contract spec;
    uint64_t last_id, last_capture_ms, last_clock_ms;
    bool cleanup_failed;
} apd_rknn_engine;
/* Fresh object must be zero-initialized, then opened ONCE. No copying, sharing,
 * concurrent calls or memset/reset while resources are live. Failure -> FAULT;
 * caller MUST close even after partial open. No implicit retry/restart. */
bool apd_rknn_open(apd_rknn_engine *engine, const char *verified_model_path,
                   const apd_rknn_contract *contract);
/* One pre-letterboxed, UPRIGHT RGB888 frame; tight source rows, exact bytes.
 * Runtime input padding is zeroed then copied row by row. clock_ms must use a
 * genuine monotonic capture clock, not wall time, and cannot reenter this engine.
 * Blocking rknn_run with 1..1000 ms requested timeout; firmware enforcement and
 * cache coherency remain UNTESTED. Timeout/failure -> FAULT, never stale output.
 * On success out points to OWNED reusable memory: decode before next infer/close.
 * Frame ID strictly increases and is consumed at attempt (not only success).
 * On ANY failure out is cleared; caller must invalidate tracker/report, then
 * close. There is no NO_PERSON inference from an error/timeout/unsupported layout.
 * out, RGB and contract buffers must NOT alias engine or tensor memory. */
bool apd_rknn_infer(apd_rknn_engine *engine, const uint8_t *rgb, size_t bytes,
    uint64_t frame_id, uint64_t captured_ms, uint32_t timeout_ms,
    uint64_t (*clock_ms)(void *), void *clock_context, apd_grid_input *out);
/* Reverse-order memory then context cleanup, attempted once per handle.
 * Return false on ANY destroy failure, including on subsequent close calls.
 * Failed destroy consumption is SDK-specific; do not retry possibly-freed handles
 * or claim zero leak. Process recovery requires validated target supervision. */
bool apd_rknn_close(apd_rknn_engine *engine);
#endif
