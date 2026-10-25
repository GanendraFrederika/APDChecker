#include "rknn_engine.h"
#include <math.h>
#include <string.h>

static bool contract_ok(const apd_rknn_contract *s) {
    if (!s || !s->model_and_sdk_verified ||
        s->contract != APD_GRID_POSTSIGMOID_I8_NCHW_7 ||
        !s->width || !s->height || s->width > 1024 || s->height > 1024 ||
        s->width % 32 || s->height % 32 || !s->max_age_ms || s->max_age_ms > 750 ||
        !s->max_io_bytes || s->max_io_bytes > APD_RKNN_MAX_IO_BYTES ||
        !isfinite(s->score_threshold) || s->score_threshold <= 0 || s->score_threshold > 1 ||
        !isfinite(s->nms_iou) || s->nms_iou <= 0 || s->nms_iou >= 1 ||
        !s->api_version[0] || !memchr(s->api_version, 0, sizeof(s->api_version)) ||
        !s->driver_version[0] || !memchr(s->driver_version, 0, sizeof(s->driver_version)))
        return false;
    for (size_t i = 0; i < APD_GRID_HEADS; ++i) {
        uint32_t stride = s->head[i].stride;
        float scale = s->head[i].scale;
        int32_t zp = s->head[i].zp;
        if ((stride != 8 && stride != 16 && stride != 32) || zp < -128 || zp > 127 ||
            !isfinite(scale) || scale <= 0 || scale > 0.0625f) return false;
        float eps = scale * 0.5f + 0.000001f;
        if ((-128 - zp) * scale > eps || (127 - zp) * scale < 1 - eps) return false;
        for (size_t j = 0; j < i; ++j) if (s->head[j].stride == stride) return false;
        for (size_t a = 0; a < APD_GRID_ANCHORS; ++a)
            for (size_t axis = 0; axis < 2; ++axis)
                if (!isfinite(s->head[i].anchors[a][axis]) ||
                    s->head[i].anchors[a][axis] <= 0 || s->head[i].anchors[a][axis] > 8192)
                    return false;
    }
    return true;
}
static bool input_ok(const rknn_tensor_attr *a, const apd_rknn_contract *s) {
    uint32_t stride = a->w_stride ? a->w_stride : s->width;
    /* Restrict physical stride to logical width + at most 64 pixels; broader
     * layouts need a separate validated adapter, not guessed packing. */
    if (a->index || a->n_dims != 4 || a->fmt != RKNN_TENSOR_NHWC ||
        (a->type != RKNN_TENSOR_INT8 && a->type != RKNN_TENSOR_UINT8) ||
        a->dims[0] != 1 || a->dims[1] != s->height || a->dims[2] != s->width || a->dims[3] != 3 ||
        stride < s->width || stride > s->width + 64 ||
        (a->h_stride && a->h_stride != s->height)) return false;
    uint32_t tight = s->width * s->height * 3;
    return a->n_elems == tight && a->size == tight &&
           a->size_with_stride == stride * s->height * 3;
}
static bool output_ok(const rknn_tensor_attr *a, const apd_rknn_contract *s, size_t i) {
    uint32_t w = s->width / s->head[i].stride, h = s->height / s->head[i].stride;
    uint32_t n = APD_GRID_CHANNELS * w * h;
    return a->index == i && a->n_dims == 4 && a->fmt == RKNN_TENSOR_NCHW &&
        a->type == RKNN_TENSOR_INT8 && a->qnt_type == RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC &&
        a->dims[0] == 1 && a->dims[1] == APD_GRID_CHANNELS && a->dims[2] == h && a->dims[3] == w &&
        a->n_elems == n && a->size == n && a->size_with_stride == n &&
        (!a->w_stride || a->w_stride == w) && (!a->h_stride || a->h_stride == h) &&
        a->zp == s->head[i].zp && a->scale == s->head[i].scale;
}
static bool same_output(const rknn_tensor_attr *a, const rknn_tensor_attr *b) {
    return a->n_dims == b->n_dims && !memcmp(a->dims, b->dims, 4 * sizeof(a->dims[0])) &&
        a->fmt == b->fmt && a->type == b->type && a->qnt_type == b->qnt_type &&
        a->zp == b->zp && a->scale == b->scale && a->size == b->size &&
        a->size_with_stride == b->size_with_stride;
}
bool apd_rknn_open(apd_rknn_engine *e, const char *model, const apd_rknn_contract *s) {
    if (!e || e->state != APD_RKNN_NEW) return false;
    e->state = APD_RKNN_FAULT;
    if (!model || !model[0] || !contract_ok(s)) return false;
    e->spec = *s;
    if (rknn_init(&e->ctx, (void *)model, 0, 0, NULL) != RKNN_SUCC || !e->ctx) return false;
    rknn_sdk_version version;
    memset(&version, 0, sizeof(version));
    if (rknn_query(e->ctx, RKNN_QUERY_SDK_VERSION, &version, sizeof(version)) != RKNN_SUCC ||
        !memchr(version.api_version, 0, sizeof(version.api_version)) ||
        !memchr(version.drv_version, 0, sizeof(version.drv_version)) ||
        strcmp(version.api_version, s->api_version) || strcmp(version.drv_version, s->driver_version))
        return false;
    rknn_input_output_num count;
    memset(&count, 0, sizeof(count));
    if (rknn_query(e->ctx, RKNN_QUERY_IN_OUT_NUM, &count, sizeof(count)) != RKNN_SUCC ||
        count.n_input != 1 || count.n_output != APD_GRID_HEADS) return false;
    if (rknn_query(e->ctx, RKNN_QUERY_NATIVE_INPUT_ATTR, &e->input, sizeof(e->input)) != RKNN_SUCC ||
        !input_ok(&e->input, s)) return false;
    uint32_t total = e->input.size_with_stride;
    if (total > s->max_io_bytes) return false;
    for (size_t i = 0; i < APD_GRID_HEADS; ++i) {
        rknn_tensor_attr logical;
        memset(&logical, 0, sizeof(logical)); logical.index = (uint32_t)i;
        e->output[i].index = (uint32_t)i;
        if (rknn_query(e->ctx, RKNN_QUERY_OUTPUT_ATTR, &logical, sizeof(logical)) != RKNN_SUCC ||
            !output_ok(&logical, s, i) ||
            rknn_query(e->ctx, RKNN_QUERY_NATIVE_OUTPUT_ATTR, &e->output[i], sizeof(e->output[i])) != RKNN_SUCC ||
            !output_ok(&e->output[i], s, i) || !same_output(&logical, &e->output[i]) ||
            logical.size_with_stride > s->max_io_bytes - total) return false;
        total += logical.size_with_stride;
    }
    /* SDK UINT8 input conversion/fused normalization, following RV1103
     * reference; caller must validate exact normalization and coherency on board.
     * Do not blindly treat the native INT8 tensor as raw UINT8 pass-through. */
    e->input.type = RKNN_TENSOR_UINT8; e->input.pass_through = 0;
    for (size_t i = 0; i < 1 + APD_GRID_HEADS; ++i) {
        rknn_tensor_attr *a = i ? &e->output[i - 1] : &e->input;
        e->mem[i] = rknn_create_mem(e->ctx, a->size_with_stride);
        if (!e->mem[i] || !e->mem[i]->virt_addr || e->mem[i]->size < a->size_with_stride ||
            rknn_set_io_mem(e->ctx, e->mem[i], a) != RKNN_SUCC) return false;
    }
    e->state = APD_RKNN_READY;
    return true;
}
bool apd_rknn_infer(apd_rknn_engine *e, const uint8_t *rgb, size_t bytes,
    uint64_t id, uint64_t captured, uint32_t timeout,
    uint64_t (*clock_ms)(void *), void *clock_context, apd_grid_input *out) {
    if (out) memset(out, 0, sizeof(*out));
    if (!e || e->state != APD_RKNN_READY) return false;
    /* All failure branches retain owned handles for a single explicit close. */
    e->state = APD_RKNN_FAULT;
    if (!rgb || !out || !clock_ms || !id || id <= e->last_id ||
        captured < e->last_capture_ms || !timeout || timeout > 1000 ||
        bytes != (size_t)e->spec.width * e->spec.height * 3) return false;
    uint64_t before = clock_ms(clock_context);
    if (before < e->last_clock_ms || before < captured || before - captured > e->spec.max_age_ms)
        return false;
    e->last_id = id; e->last_capture_ms = captured; e->last_clock_ms = before;
    memset(e->mem[0]->virt_addr, 0, e->input.size_with_stride);
    size_t row = (size_t)e->spec.width * 3;
    size_t stride = (size_t)(e->input.w_stride ? e->input.w_stride : e->spec.width) * 3;
    for (size_t y = 0; y < e->spec.height; ++y)
        memcpy((uint8_t *)e->mem[0]->virt_addr + y * stride, rgb + y * row, row);
    rknn_run_extend run;
    memset(&run, 0, sizeof(run)); run.timeout_ms = (int32_t)timeout; run.fence_fd = -1;
    if (rknn_run(e->ctx, &run) != RKNN_SUCC) return false;
    uint64_t after = clock_ms(clock_context);
    if (after < before || after < captured || after - captured > e->spec.max_age_ms ||
        after - before > timeout) return false;
    e->last_clock_ms = after;
    out->contract = e->spec.contract; out->input_width = e->spec.width; out->input_height = e->spec.height;
    out->score_threshold = e->spec.score_threshold; out->nms_iou = e->spec.nms_iou;
    for (size_t i = 0; i < APD_GRID_HEADS; ++i) {
        apd_grid_head *h = &out->heads[i];
        h->data = (const int8_t *)e->mem[i + 1]->virt_addr;
        h->byte_count = e->output[i].size_with_stride;
        h->grid_width = e->output[i].dims[3]; h->grid_height = e->output[i].dims[2];
        h->row_stride = h->grid_width; h->channel_stride = h->row_stride * h->grid_height;
        h->pixel_stride = e->spec.head[i].stride;
        h->zero_point = e->output[i].zp; h->scale = e->output[i].scale;
        memcpy(h->anchors, e->spec.head[i].anchors, sizeof(h->anchors));
    }
    e->state = APD_RKNN_READY;
    return true;
}
bool apd_rknn_close(apd_rknn_engine *e) {
    if (!e) return false;
    if (e->state == APD_RKNN_CLOSED) return !e->cleanup_failed;
    for (size_t n = 1 + APD_GRID_HEADS; n > 0; --n) {
        size_t i = n - 1;
        if (e->mem[i]) {
            if (rknn_destroy_mem(e->ctx, e->mem[i]) != RKNN_SUCC) e->cleanup_failed = true;
            e->mem[i] = NULL;
        }
    }
    if (e->ctx) {
        if (rknn_destroy(e->ctx) != RKNN_SUCC) e->cleanup_failed = true;
        e->ctx = 0;
    }
    e->state = APD_RKNN_CLOSED;
    return !e->cleanup_failed;
}
