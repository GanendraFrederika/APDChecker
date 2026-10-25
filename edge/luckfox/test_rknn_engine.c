/* HOST fault injection against pinned reference header. No real RKNN linked. */
#include "rknn_engine.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int operation, fail_at, mode, live_mem, live_ctx, created, destroyed, run_calls;
static int destroy_error, context_error, open_error_with_handle;
static rknn_tensor_mem *slots[4];
static uint64_t ticks[2]; static unsigned tick_index;
static int step(void) { ++operation; return operation == fail_at; }
static void reset_mock(void) {
    assert(!live_mem && !live_ctx);
    operation = fail_at = mode = created = destroyed = run_calls = 0;
    destroy_error = context_error = open_error_with_handle = 0;
    memset(slots, 0, sizeof(slots)); ticks[0] = 100; ticks[1] = 110; tick_index = 0;
}
static uint64_t clock_mock(void *arg) { (void)arg; assert(tick_index < 2); return ticks[tick_index++]; }
static apd_rknn_contract spec(void) {
    apd_rknn_contract s; memset(&s, 0, sizeof(s));
    s.model_and_sdk_verified = true; /* test fixture only */
    s.contract = APD_GRID_POSTSIGMOID_I8_NCHW_7; s.width = s.height = 32;
    s.max_age_ms = 750; s.max_io_bytes = 10000;
    s.score_threshold = 0.4f; s.nms_iou = 0.5f;
    strcpy(s.api_version, "TEST-API"); strcpy(s.driver_version, "TEST-DRIVER");
    for (unsigned i = 0; i < 3; ++i) {
        s.head[i].stride = 8u << i; s.head[i].zp = -128; s.head[i].scale = 1.0f / 255;
        for (unsigned a = 0; a < 3; ++a) s.head[i].anchors[a][0] = s.head[i].anchors[a][1] = 8;
    }
    return s;
}
int rknn_init(rknn_context *ctx, void *model, uint32_t size, uint32_t flags, rknn_init_extend *ext) {
    assert(model && !size && !flags && !ext && !live_ctx);
    if (step() && !open_error_with_handle) return RKNN_ERR_FAIL;
    *ctx = 42; live_ctx = 1;
    return open_error_with_handle ? RKNN_ERR_FAIL : RKNN_SUCC;
}
int rknn_query(rknn_context ctx, rknn_query_cmd cmd, void *out, uint32_t size) {
    assert(ctx == 42 && live_ctx); if (step()) return RKNN_ERR_FAIL;
    if (cmd == RKNN_QUERY_SDK_VERSION) {
        assert(size == sizeof(rknn_sdk_version)); rknn_sdk_version *v = out;
        strcpy(v->api_version, mode == 1 ? "WRONG" : "TEST-API");
        strcpy(v->drv_version, mode == 2 ? "WRONG" : "TEST-DRIVER");
        if (mode == 3) memset(v->api_version, 'x', sizeof(v->api_version));
        return 0;
    }
    if (cmd == RKNN_QUERY_IN_OUT_NUM) {
        assert(size == sizeof(rknn_input_output_num)); rknn_input_output_num *n = out;
        n->n_input = mode == 4 ? 2 : 1; n->n_output = mode == 5 ? 4 : 3; return 0;
    }
    assert(size == sizeof(rknn_tensor_attr)); rknn_tensor_attr *a = out;
    unsigned index = a->index; memset(a, 0, sizeof(*a)); a->index = index; a->n_dims = 4;
    a->dims[0] = 1;
    if (cmd == RKNN_QUERY_NATIVE_INPUT_ATTR) {
        a->fmt = RKNN_TENSOR_NHWC; a->type = RKNN_TENSOR_INT8;
        a->dims[1] = a->dims[2] = 32; a->dims[3] = 3;
        a->n_elems = a->size = 3072; a->w_stride = 34; a->size_with_stride = 3264;
        if (mode == 6) a->fmt = RKNN_TENSOR_NCHW;
        if (mode == 7) a->w_stride = UINT32_MAX;
        if (mode == 8) a->h_stride = 33;
        if (mode == 9) a->size_with_stride = 3072;
        if (mode == 10) a->type = RKNN_TENSOR_FLOAT32;
        if (mode == 11) a->dims[3] = 4;
        if (mode == 12) a->n_elems = UINT32_MAX;
        if (mode == 25) a->index = 1;
    } else {
        assert(index < 3 && (cmd == RKNN_QUERY_OUTPUT_ATTR || cmd == RKNN_QUERY_NATIVE_OUTPUT_ATTR));
        a->fmt = RKNN_TENSOR_NCHW; a->type = RKNN_TENSOR_INT8;
        a->qnt_type = RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC;
        a->dims[1] = 36; a->dims[2] = a->dims[3] = 4u >> index;
        a->n_elems = a->size = a->size_with_stride = 36 * a->dims[2] * a->dims[3];
        a->zp = -128; a->scale = 1.0f / 255;
        if (mode == 13) a->fmt = RKNN_TENSOR_NHWC;
        if (mode == 14 && cmd == RKNN_QUERY_NATIVE_OUTPUT_ATTR) a->fmt = RKNN_TENSOR_NC1HWC2;
        if (mode == 15) a->type = RKNN_TENSOR_UINT8;
        if (mode == 16) a->qnt_type = RKNN_TENSOR_QNT_NONE;
        if (mode == 17) a->zp = -127;
        if (mode == 18) a->scale = 0.01f;
        if (mode == 19) a->dims[1] = 255;
        if (mode == 20) a->size_with_stride = UINT32_MAX;
        if (mode == 21) a->w_stride = 100;
        if (mode == 22) a->n_elems = 1;
        if (mode == 23) a->index = 3;
        if (mode == 24) a->dims[0] = 2;
    }
    return 0;
}
rknn_tensor_mem *rknn_create_mem(rknn_context ctx, uint32_t size) {
    assert(ctx == 42 && live_ctx && created < 4);
    if (step()) return NULL;
    rknn_tensor_mem *m = calloc(1, sizeof(*m)); assert(m);
    m->virt_addr = malloc(size); assert(m->virt_addr); memset(m->virt_addr, 0x7f, size);
    m->size = size; m->priv_data = (void *)(uintptr_t)(created + 1); slots[created++] = m; ++live_mem;
    if (mode == 26) m->size = 1;
    if (mode == 27) { free(m->virt_addr); m->virt_addr = NULL; }
    return m;
}
int rknn_set_io_mem(rknn_context ctx, rknn_tensor_mem *m, rknn_tensor_attr *attr) {
    assert(ctx == 42 && live_ctx && m);
    if (created == 1) assert(attr->type == RKNN_TENSOR_UINT8 && !attr->pass_through && attr->fmt == RKNN_TENSOR_NHWC);
    else assert(attr->type == RKNN_TENSOR_INT8 && attr->fmt == RKNN_TENSOR_NCHW);
    return step() ? RKNN_ERR_FAIL : 0;
}
int rknn_run(rknn_context ctx, rknn_run_extend *extend) {
    assert(ctx == 42 && live_mem == 4 && extend && !extend->non_block &&
           extend->timeout_ms == 100 && extend->fence_fd == -1);
    ++run_calls; if (step()) return RKNN_ERR_TIMEOUT;
    for (unsigned i = 1; i < 4; ++i) memset(slots[i]->virt_addr, 0x80, slots[i]->size);
    extend->frame_id = 999; /* opaque runtime ID is not a camera capture timestamp */
    return 0;
}
int rknn_destroy_mem(rknn_context ctx, rknn_tensor_mem *m) {
    assert(ctx == 42 && live_ctx && live_mem > 0);
    assert((uintptr_t)m->priv_data == (unsigned)(created - destroyed));
    ++destroyed; --live_mem; free(m->virt_addr); free(m);
    return destroy_error ? RKNN_ERR_FAIL : 0; /* mock CONSUMES even on error */
}
int rknn_destroy(rknn_context ctx) {
    assert(ctx == 42 && live_ctx && !live_mem); live_ctx = 0;
    return context_error ? RKNN_ERR_FAIL : 0;
}
static void infer_failure(int kind) {
    reset_mock(); apd_rknn_engine e = {0}; apd_rknn_contract s = spec();
    assert(apd_rknn_open(&e, "/tmp/test-only.rknn", &s));
    uint8_t rgb[3072] = {0}; apd_grid_input out; memset(&out, 0xff, sizeof(out));
    uint64_t id = 1, captured = 100; size_t bytes = sizeof(rgb); uint32_t timeout = 100;
    if (kind == 0) fail_at = operation + 1;
    if (kind == 1) id = 0;
    if (kind == 2) captured = 101;
    if (kind == 3) ticks[0] = 900;
    if (kind == 4) ticks[1] = 99;
    if (kind == 5) ticks[1] = 851;
    if (kind == 6) ticks[1] = 201;
    if (kind == 7) bytes = 3071;
    if (kind == 8) timeout = 0;
    if (kind == 9) timeout = 1001;
    assert(!apd_rknn_infer(&e, rgb, bytes, id, captured, timeout, clock_mock, NULL, &out));
    apd_grid_input zero; memset(&zero, 0, sizeof(zero)); assert(!memcmp(&out, &zero, sizeof(out)));
    assert(e.state == APD_RKNN_FAULT); assert(apd_rknn_close(&e));
    assert(!live_mem && !live_ctx && apd_rknn_close(&e));
}
int main(void) {
    reset_mock(); apd_rknn_engine e = {0}; apd_rknn_contract s = spec();
    assert(apd_rknn_open(&e, "/tmp/test-only.rknn", &s)); int steps = operation;
    uint8_t rgb[3072]; memset(rgb, 37, sizeof(rgb)); apd_grid_input out;
    assert(apd_rknn_infer(&e, rgb, sizeof(rgb), 1, 100, 100, clock_mock, NULL, &out));
    for (unsigned y = 0; y < 32; ++y) {
        const uint8_t *p = (const uint8_t *)e.mem[0]->virt_addr + y * 102;
        for (unsigned x = 0; x < 96; ++x) assert(p[x] == 37);
        for (unsigned x = 96; x < 102; ++x) assert(p[x] == 0);
    }
    apd_grid_workspace workspace; apd_raw_detection detections[72]; size_t count = 99;
    assert(apd_grid_decode(&out, &workspace, detections, 72, &count) && count == 0);
    /* Open is not a destructive replacement of a live engine. */
    assert(!apd_rknn_open(&e, "/tmp/test-only.rknn", &s) && e.state == APD_RKNN_READY);
    assert(!apd_rknn_infer(&e, rgb, sizeof(rgb), 1, 100, 100, clock_mock, NULL, &out));
    assert(!out.heads[0].data && run_calls == 1 && e.state == APD_RKNN_FAULT);
    assert(apd_rknn_close(&e)); assert(apd_rknn_close(&e));
    assert(!apd_rknn_open(&e, "/tmp/test-only.rknn", &s));
    for (int fail = 1; fail <= steps; ++fail) {
        reset_mock(); memset(&e, 0, sizeof(e)); fail_at = fail;
        assert(!apd_rknn_open(&e, "/tmp/test-only.rknn", &s));
        assert(e.state == APD_RKNN_FAULT && apd_rknn_close(&e) && apd_rknn_close(&e));
        assert(!live_mem && !live_ctx);
    }
    for (int bad = 1; bad <= 27; ++bad) {
        reset_mock(); memset(&e, 0, sizeof(e)); mode = bad;
        assert(!apd_rknn_open(&e, "/tmp/test-only.rknn", &s));
        assert(apd_rknn_close(&e) && !live_mem && !live_ctx);
    }
    reset_mock(); memset(&e, 0, sizeof(e)); open_error_with_handle = 1;
    assert(!apd_rknn_open(&e, "/tmp/test-only.rknn", &s)); assert(apd_rknn_close(&e));
    for (int kind = 0; kind < 10; ++kind) infer_failure(kind);
    for (unsigned kind = 0; kind < 2; ++kind) {
        reset_mock(); memset(&e, 0, sizeof(e)); assert(apd_rknn_open(&e, "/tmp/test-only.rknn", &s));
        if (kind) context_error = 1; else destroy_error = 1;
        assert(!apd_rknn_close(&e)); int attempts = destroyed;
        assert(!apd_rknn_close(&e) && attempts == destroyed); assert(!live_mem && !live_ctx);
    }
    /* Manifest/SDK gate must prevent even rknn_init. */
    for (unsigned kind = 0; kind < 7; ++kind) {
        reset_mock(); memset(&e, 0, sizeof(e)); s = spec();
        if (kind == 0) s.model_and_sdk_verified = false;
        if (kind == 1) s.width = 33;
        if (kind == 2) s.head[1].stride = 8;
        if (kind == 3) s.head[0].scale = 0;
        if (kind == 4) s.head[0].anchors[0][0] = 0;
        if (kind == 5) memset(s.api_version, 'x', sizeof(s.api_version));
        if (kind == 6) s.max_io_bytes = APD_RKNN_MAX_IO_BYTES + 1;
        assert(!apd_rknn_open(&e, "/tmp/test-only.rknn", &s) && operation == 0);
        assert(apd_rknn_close(&e));
    }
    reset_mock(); memset(&e, 0, sizeof(e)); s = spec(); s.max_io_bytes = 3500;
    assert(!apd_rknn_open(&e, "/tmp/test-only.rknn", &s));
    assert(created == 0 && apd_rknn_close(&e));
    printf("RKNN engine HOST PASS: %d open-operation failures, 27 tensor/version faults, 10 run/freshness faults; NO real runtime/model/camera.\n", steps);
    return 0;
}
