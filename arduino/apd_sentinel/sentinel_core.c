/* APD Sentinel MCU core. See sentinel_core.h and docs/sentinel/PROTOCOL.md. */
#include "sentinel_core.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#if defined(__AVR__)
#include <avr/pgmspace.h>
#define SC_P(s) PSTR(s)
#define sc_snprintf snprintf_P
#define sc_strcmp_p strcmp_P
#define sc_strncpy_p strncpy_P
#else
#define SC_P(s) (s)
#define sc_snprintf snprintf
#define sc_strcmp_p strcmp
#define sc_strncpy_p strncpy
#endif

#define EPS 0.01f
/* Flash is tight on the Uno: keep big helpers out-of-line (no code duplication). */
#define SC_NOINLINE __attribute__((noinline))
#define TOK_ZERO 0UL

/* ------------------------------------------------------------ framing */

uint8_t sc_crc8(const char *data, uint8_t len) {
  uint8_t v = 0;
  for (uint8_t i = 0; i < len; ++i) {
    v ^= (uint8_t)data[i];
    for (uint8_t b = 0; b < 8; ++b) v = (uint8_t)((v & 0x80) ? (v << 1) ^ 0x07 : (v << 1));
  }
  return v;
}

void sc_framer_init(sc_framer *f) { memset(f, 0, sizeof(*f)); }

static int hexval(char ch) {
  if (ch >= '0' && ch <= '9') return ch - '0';
  if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
  return -1;               /* lowercase hex is a format error by contract */
}

int sc_framer_feed(sc_framer *f, char ch, uint32_t now_ms, char *body_out) {
  /* A stalled sender cannot keep a half frame alive (slow-drip protection). */
  if (f->active && (uint32_t)(now_ms - f->last_ms) > SC_INTERBYTE_MS) f->active = false;
  if (ch == '$') {
    f->active = true; f->console = false; f->overflow = false; f->len = 0; f->last_ms = now_ms;
    return SC_NONE;
  }
  if (!f->active) {
    if (ch == '#') {          /* human console line, no CRC (FIRMWARE_SPEC 9) */
      f->active = true; f->console = true; f->overflow = false; f->len = 0; f->last_ms = now_ms;
    }
    return SC_NONE;
  }
  f->last_ms = now_ms;
  if (ch == '\n') {
    uint8_t len = f->len;
    f->active = false;
    if (f->overflow) return SC_OVERFLOW;
    if (len && f->buf[len - 1] == '\r') --len;
    if (f->console) {
      if (len == 0) return SC_NONE;
      if (len > SC_BODY_MAX) return SC_OVERFLOW;
      memcpy(body_out, f->buf, len);
      body_out[len] = '\0';
      return SC_CONSOLE;
    }
    if (len < 4 || f->buf[len - 3] != '*') return SC_BAD_FORMAT;
    uint8_t body = (uint8_t)(len - 3);
    if (body > SC_BODY_MAX) return SC_OVERFLOW;
    for (uint8_t i = 0; i < body; ++i) {
      char b = f->buf[i];
      if (b < 0x20 || b > 0x7E || b == '*') return SC_BAD_FORMAT;
    }
    int hi = hexval(f->buf[len - 2]), lo = hexval(f->buf[len - 1]);
    if (hi < 0 || lo < 0) return SC_BAD_FORMAT;
    if (sc_crc8(f->buf, body) != (uint8_t)((hi << 4) | lo)) return SC_BAD_CRC;
    memcpy(body_out, f->buf, body);
    body_out[body] = '\0';
    return SC_FRAME;
  }
  if (f->len >= sizeof(f->buf)) { f->overflow = true; return SC_NONE; }
  f->buf[f->len++] = ch;
  return SC_NONE;
}

/* ------------------------------------------------------------ safe zone */

void sc_limits_default(sc_limits *l) {
  /* Measured by the user on 24-10-2026 (PROTOCOL.md section 5). */
  l->pmin = 0; l->phome = 900; l->pmax = 1450;
  l->tmin0 = 1450; l->tmin1 = 1000; l->thome = 1800; l->tmax = 1800;  /* home: level (development rig) */
  l->pvmax = 120; l->tvmax = 90; l->pacc = 300; l->tacc = 200;   /* 27-10: softer starts */
  l->tmaxr = 1700;                 /* 26-10-2026: looking hard right, 170 deg is the top */
}

static int32_t ceil_div(int32_t a, int32_t b) { return a >= 0 ? (a + b - 1) / b : -((-a) / b); }

int16_t sc_tilt_floor_i(const sc_limits *l, int16_t pan) {
  if (pan < l->pmin) pan = l->pmin;
  if (pan > l->pmax) pan = l->pmax;
  return (int16_t)(l->tmin0 + ceil_div((int32_t)(l->tmin1 - l->tmin0) * (pan - l->pmin),
                                      (int32_t)(l->pmax - l->pmin)));
}

/* y at x on the segment (x0,y0)-(x1,y1), x0 < x1, held flat outside it. Shared by the
 * floor, the ceiling and their inverses (the zone walls) to save flash. */
SC_NOINLINE static float seg(float x, int16_t x0, int16_t x1, int16_t y0, int16_t y1) {
  if (x >= x1) return y1;
  if (x <= x0) return y0;
  return (float)y0 + (float)(y1 - y0) * (x - (float)x0) / (float)(x1 - x0);
}

float sc_tilt_floor_f(const sc_limits *l, float pan) { return seg(pan, l->pmin, l->pmax, l->tmin0, l->tmin1); }

/* Ceiling: tmaxr at pmin rising linearly to tmax at phome, flat tmax beyond. A concave
 * ceiling over a linear floor keeps the zone convex (see smooth_axis). */
int16_t sc_tilt_ceil_i(const sc_limits *l, int16_t pan) {
  if (pan < l->pmin) pan = l->pmin;
  if (pan >= l->phome) return l->tmax;     /* also covers phome == pmin (no division by 0) */
  return (int16_t)(l->tmaxr + (int32_t)(l->tmax - l->tmaxr) * (pan - l->pmin) / (l->phome - l->pmin));
}

float sc_tilt_ceil_f(const sc_limits *l, float pan) { return seg(pan, l->pmin, l->phome, l->tmaxr, l->tmax); }

static bool in_dd(int16_t v) { return v >= 0 && v <= 1800; }

bool sc_limits_valid(const sc_limits *l) {
  if (!in_dd(l->pmin) || !in_dd(l->phome) || !in_dd(l->pmax) || !in_dd(l->tmin0) ||
      !in_dd(l->tmin1) || !in_dd(l->thome) || !in_dd(l->tmax)) return false;
  if (l->pmin >= l->pmax || l->phome < l->pmin || l->phome > l->pmax) return false;
  if (l->tmin0 >= l->tmaxr || l->tmaxr > l->tmax || l->tmin1 >= l->tmax) return false;
  if (l->thome < sc_tilt_floor_i(l, l->phome) || l->thome > l->tmax) return false;
  if (l->pvmax < 10 || l->pvmax > 600 || l->tvmax < 10 || l->tvmax > 600) return false;
  if (l->pacc < 50 || l->pacc > 3000 || l->tacc < 50 || l->tacc > 3000) return false;
  return true;
}

bool sc_in_zone(const sc_limits *l, float pan, float tilt) {
  return pan >= l->pmin - EPS && pan <= l->pmax + EPS &&
         tilt >= sc_tilt_floor_f(l, pan) - EPS && tilt <= sc_tilt_ceil_f(l, pan) + EPS;
}

void sc_clamp(const sc_limits *l, int16_t *pan, int16_t *tilt, bool *clamped) {
  int16_t p = *pan, t = *tilt;
  if (p < l->pmin) p = l->pmin;
  if (p > l->pmax) p = l->pmax;
  int16_t floor_i = sc_tilt_floor_i(l, p), ceil_i = sc_tilt_ceil_i(l, p);
  if (t < floor_i) t = floor_i;
  if (t > ceil_i) t = ceil_i;
  *clamped = (p != *pan) || (t != *tilt);
  *pan = p;
  *tilt = t;
}

uint16_t sc_dd_to_us(float dd) {
  if (dd < 0) dd = 0;
  if (dd > 1800) dd = 1800;
  /* Same 544..2400 us map as Servo.write(), at 0.1 degree resolution. */
  return (uint16_t)(544.0f + dd * (1856.0f / 1800.0f) + 0.5f);
}

/* ------------------------------------------------------------ emit helpers */

static void emit(sc_ctx *c, const char *body) {
  if (c->hooks.emit) c->hooks.emit(c->hooks.user, body);
}

static void copy_p(char *dst, const char *src_p, size_t n) {
  sc_strncpy_p(dst, src_p, n - 1);
  dst[n - 1] = '\0';
}

static void emit_p(sc_ctx *c, const char *body_p) {
  char b[40];
  copy_p(b, body_p, sizeof(b));
  emit(c, b);
}

static void err_p(sc_ctx *c, const char *code_p, uint32_t now_ms) {
  if ((uint32_t)(now_ms - c->err_window_ms) >= 1000UL) { c->err_window_ms = now_ms; c->err_count = 0; }
  if (c->err_count >= 4) return;     /* max 4 ERR frames per second */
  ++c->err_count;
  char code[12], b[24];
  copy_p(code, code_p, sizeof(code));
  sc_snprintf(b, sizeof(b), SC_P("ERR,%s"), code);
  emit(c, b);
}

static void ack(sc_ctx *c, const char *cmd, bool ok, const char *detail) {
  char b[48];
  sc_snprintf(b, sizeof(b), SC_P("ACK,%s,%s,%s"), cmd, ok ? "OK" : "ERR", detail);
  emit(c, b);
}

static void ack_p(sc_ctx *c, const char *cmd, bool ok, const char *detail_p) {
  char d[12];
  copy_p(d, detail_p, sizeof(d));
  ack(c, cmd, ok, d);
}

void sc_emit_ready(sc_ctx *c) {
  char b[48];
  sc_snprintf(b, sizeof(b), SC_P("READY,SENTINEL,%s,%08lX,%d"), SC_VERSION,
              (unsigned long)(c->session ? c->token : TOK_ZERO), c->calibrated ? 1 : 0);
  emit(c, b);
}

void sc_emit_lim(sc_ctx *c) {
  const sc_limits *l = &c->lim;
  char b[96];
  sc_snprintf(b, sizeof(b), SC_P("LIM,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d"),
              l->pmin, l->phome, l->pmax, l->tmin0, l->tmin1, l->thome, l->tmax,
              l->pvmax, l->tvmax, l->pacc, l->tacc, l->tmaxr, c->calibrated ? 1 : 0);
  emit(c, b);
}

static void fmt_temp(char *out, size_t n, int16_t dc) {
  if (dc == SC_TEMP_NA) { out[0] = 'N'; out[1] = 'A'; out[2] = '\0'; }
  else sc_snprintf(out, n, SC_P("%d"), dc);
}

static int16_t round_dd(float v) { return (int16_t)(v >= 0 ? v + 0.5f : v - 0.5f); }

void sc_emit_telemetry(sc_ctx *c, uint32_t now_ms, const sc_hw *hw) {
  uint8_t flags = 0;
  if (c->session) flags |= 0x01;
  if (c->link_ok) flags |= 0x02;
  if (hw->sounding) flags |= 0x04;
  if (hw->relay) flags |= 0x08;
  if (c->moving) flags |= 0x10;
  if (c->cal_mode) flags |= 0x20;
  if (hw->lcd_ok) flags |= 0x40;
  if (c->clamped) flags |= 0x80;
  char ta[8], tp[8], b[96];
  fmt_temp(ta, sizeof(ta), hw->temp_a);
  fmt_temp(tp, sizeof(tp), hw->temp_p);
  sc_snprintf(b, sizeof(b), SC_P("T,%lu,%d,%d,%d,%d,%02X,%s,%s,%u,%u,%u,%u"),
              (unsigned long)now_ms, round_dd(c->pan.out), round_dd(c->tilt.out),
              round_dd(c->pan.target), round_dd(c->tilt.target), flags, ta, tp,
              (unsigned)hw->fan_a, (unsigned)hw->fan_p, (unsigned)hw->vcc_mv,
              (unsigned)(c->have_seq ? c->last_seq : 0));
  emit(c, b);
}

/* ------------------------------------------------------------ parsing */

enum { PI_OK = 0, PI_FMT = 1, PI_RANGE = 2 };

static uint8_t parse_int(const char *s, int32_t lo, int32_t hi, int32_t *out) {
  bool neg = false;
  uint8_t digits = 0;
  int32_t v = 0;
  if (*s == '-') { neg = true; ++s; }
  while (*s) {
    if (*s < '0' || *s > '9' || ++digits > 5) return PI_FMT;
    v = v * 10 + (*s - '0');
    ++s;
  }
  if (!digits) return PI_FMT;
  if (neg) v = -v;
  if (v < lo || v > hi) return PI_RANGE;
  *out = v;
  return PI_OK;
}

static bool parse_token(const char *s, uint32_t *out) {
  uint32_t v = 0;
  uint8_t n = 0;
  for (; s[n]; ++n) {
    int h = hexval(s[n]);
    if (h < 0 || n >= 8) return false;
    v = (v << 4) | (uint32_t)h;
  }
  if (n != 8) return false;
  *out = v;
  return true;
}

static uint8_t split(char *body, char **f) {
  uint8_t n = 0;
  f[n++] = body;
  for (char *p = body; *p; ++p) {
    if (*p == ',') {
      if (n >= SC_MAX_FIELDS) return 255;
      *p = '\0';
      f[n++] = p + 1;
    }
  }
  return n;
}

static bool eq_p(const char *s, const char *lit_p) { return sc_strcmp_p(s, lit_p) == 0; }

static void range_err(sc_ctx *c, uint8_t r, uint32_t now_ms) {
  if (r == PI_FMT) err_p(c, SC_P("FMT"), now_ms);
  else err_p(c, SC_P("RANGE"), now_ms);
}

/* ------------------------------------------------------------ state changes */

static void hold_position(sc_ctx *c) {
  c->pan.target = c->pan.pos;
  c->tilt.target = c->tilt.pos;
}

static void go_home(sc_ctx *c, float speed) {
  c->pan.target = c->lim.phome;
  c->tilt.target = c->lim.thome;
  c->vlimit = speed;
}

static void reset_session_view(sc_ctx *c) {
  c->alarm = false;
  c->vox = false;
  c->mode = 'I';
  memcpy(c->items, "----", 5);
  c->fx = 0;
  c->fx_armed = false;
  c->ppl = c->viol = 0;
  c->trk = 0;
  c->clamped = false;
}

void sc_init(sc_ctx *c, const sc_hooks *hooks, uint32_t now_ms) {
  memset(c, 0, sizeof(*c));
  if (hooks) c->hooks = *hooks;
  sc_limits tmp;
  sc_limits_default(&c->lim);
  if (c->hooks.load && c->hooks.load(c->hooks.user, &tmp) && sc_limits_valid(&tmp)) {
    c->lim = tmp;
    c->calibrated = true;
  }
  c->boot_ms = now_ms;
  c->err_window_ms = now_ms;
  c->pan.pos = c->pan.target = c->pan.f1 = c->pan.out = c->lim.phome;
  c->tilt.pos = c->tilt.target = c->tilt.f1 = c->tilt.out = c->lim.thome;
  c->volume = 50;
  c->vlimit = SC_CAL_SPEED;
  c->fan_manual[0] = c->fan_manual[1] = -1;
  reset_session_view(c);
  sc_emit_ready(c);
  sc_emit_lim(c);
}

void sc_set_boot_pose(sc_ctx *c, int16_t pan, int16_t tilt) {
  if (!in_dd(pan) || !in_dd(tilt)) return;
  c->pan.pos = c->pan.f1 = c->pan.out = pan;
  c->tilt.pos = c->tilt.f1 = c->tilt.out = tilt;
  c->pan.vel = c->tilt.vel = 0;
  go_home(c, SC_CAL_SPEED);        /* slow glide; zone escape handles outside poses */
}

void sc_frame_error(sc_ctx *c, int code, uint32_t now_ms) {
  if (code == SC_BAD_CRC) err_p(c, SC_P("CRC"), now_ms);
  else if (code == SC_OVERFLOW) err_p(c, SC_P("OVF"), now_ms);
  else if (code == SC_BAD_FORMAT) err_p(c, SC_P("FMT"), now_ms);
}

/* ------------------------------------------------------------ commands */

SC_NOINLINE static void handle_s(sc_ctx *c, char **f, uint8_t n, uint32_t now_ms) {
  int32_t seq, pan, tilt, spd, ppl, viol, trk, fxid = 0;
  uint32_t tok;
  uint8_t r;
  if (c->cal_mode) { err_p(c, SC_P("MODE"), now_ms); return; }
  /* SLP/1.0 = 12 fields; SLP/1.1 adds glove (in items), fx, fx_id and vox = 15. */
  if ((n != 12 && n != 15) || !parse_token(f[1], &tok)) { err_p(c, SC_P("FMT"), now_ms); return; }
  if (!c->session || tok != c->token) { err_p(c, SC_P("TOKEN"), now_ms); return; }
  /* Validate every field before applying anything: a frame is atomic. */
  if ((r = parse_int(f[2], 1, 65535, &seq)) || (r = parse_int(f[4], 0, 1800, &pan)) ||
      (r = parse_int(f[5], 0, 1800, &tilt)) || (r = parse_int(f[6], 1, 600, &spd)) ||
      (r = parse_int(f[9], 0, 99, &ppl)) || (r = parse_int(f[10], 0, 99, &viol)) ||
      (r = parse_int(f[11], 0, 65535, &trk))) {
    range_err(c, r, now_ms);
    return;
  }
  const char *mode = f[3], *items = f[7], *alarm = f[8];
  uint8_t nitems = n == 15 ? 4 : 3;
  if (strlen(mode) != 1 || !strchr("IPATGVSF", mode[0]) || strlen(items) != nitems ||
      strlen(alarm) != 1 || (alarm[0] != '0' && alarm[0] != '1')) {
    err_p(c, SC_P("FMT"), now_ms);
    return;
  }
  for (uint8_t i = 0; i < nitems; ++i) {
    if (!strchr("PAU-", items[i])) { err_p(c, SC_P("FMT"), now_ms); return; }
  }
  char fx = '-';
  bool vox = true;
  if (n == 15) {
    if (strlen(f[12]) != 1 || !strchr("-NHCW", f[12][0]) ||
        strlen(f[14]) != 1 || (f[14][0] != '0' && f[14][0] != '1')) {
      err_p(c, SC_P("FMT"), now_ms);
      return;
    }
    if ((r = parse_int(f[13], 0, 255, &fxid))) { range_err(c, r, now_ms); return; }
    fx = f[12][0];
    vox = f[14][0] == '1';
  }
  if (alarm[0] == '1' && mode[0] != 'V') { err_p(c, SC_P("RANGE"), now_ms); return; }
  if (c->have_seq) {
    uint16_t d = (uint16_t)((uint16_t)seq - c->last_seq);
    if (d == 0 || d > 32767) { err_p(c, SC_P("SEQ"), now_ms); return; }
  }
  c->last_seq = (uint16_t)seq;
  c->have_seq = true;
  c->last_s_ms = now_ms;
  if (!c->link_ok) {
    c->link_ok = true;
    c->lost = false;
    c->lost_homing = false;
    emit_p(c, SC_P("EVT,LINK,OK"));
  }
  c->mode = mode[0];
  memcpy(c->items, items, 3);
  c->items[3] = nitems == 4 ? items[3] : '-';
  c->items[4] = '\0';
  c->vox = vox;
  /* An animation request fires once per fx_id change (the brain repeats frames at 10 Hz). */
  if (fx != '-') {
    if (!c->fx_armed || (uint8_t)fxid != c->fx_last_id) sc_fx_start(c, fx, now_ms);
    c->fx_last_id = (uint8_t)fxid;
    c->fx_armed = true;
  }
  c->alarm = alarm[0] == '1';
  c->ppl = (uint8_t)ppl;
  c->viol = (uint8_t)viol;
  c->trk = (uint16_t)trk;
  int16_t p = (int16_t)pan, t = (int16_t)tilt;
  sc_clamp(&c->lim, &p, &t, &c->clamped);
  c->sp_pan = p;
  c->sp_tilt = t;
  c->pan.target = p;
  c->tilt.target = t;
  c->vlimit = (float)spd;
}

SC_NOINLINE static void handle_hello(sc_ctx *c, char **f, uint8_t n, uint32_t now_ms) {
  uint32_t tok;
  if (n != 2 || !parse_token(f[1], &tok)) { err_p(c, SC_P("FMT"), now_ms); return; }
  if (tok == TOK_ZERO) { err_p(c, SC_P("RANGE"), now_ms); return; }
  if (c->cal_mode) { ack_p(c, f[0], false, SC_P("MODE")); return; }
  c->session = true;
  c->token = tok;
  c->have_seq = false;
  c->link_ok = false;
  c->lost = false;
  c->lost_homing = false;
  c->last_s_ms = now_ms;           /* link timeout counts from HELLO */
  reset_session_view(c);
  hold_position(c);                /* the camera stays where it is */
  sc_emit_ready(c);
  sc_emit_lim(c);
}

static bool axis_arg(const char *s, char *axis) {
  if ((s[0] == 'P' || s[0] == 'T') && s[1] == '\0') { *axis = s[0]; return true; }
  return false;
}

SC_NOINLINE static void handle_set(sc_ctx *c, char **f, uint8_t n, uint32_t now_ms) {
  char axis;
  int32_t v;
  if (n != 4 || !axis_arg(f[1], &axis)) { err_p(c, SC_P("FMT"), now_ms); return; }
  if (!c->cal_mode) { ack_p(c, f[0], false, SC_P("MODE")); return; }
  uint8_t r = parse_int(f[3], -32768, 32767, &v);
  if (r) { range_err(c, r, now_ms); return; }
  sc_limits t = c->lim;
  int16_t *slot = 0;
  const char *k = f[2];
  if (axis == 'P') {
    if (eq_p(k, SC_P("MIN"))) slot = &t.pmin;
    else if (eq_p(k, SC_P("MAX"))) slot = &t.pmax;
    else if (eq_p(k, SC_P("HOME"))) slot = &t.phome;
    else if (eq_p(k, SC_P("VMAX"))) slot = &t.pvmax;
    else if (eq_p(k, SC_P("ACC"))) slot = &t.pacc;
  } else {
    if (eq_p(k, SC_P("MIN0"))) slot = &t.tmin0;
    else if (eq_p(k, SC_P("MIN1"))) slot = &t.tmin1;
    else if (eq_p(k, SC_P("MAX"))) slot = &t.tmax;
    else if (eq_p(k, SC_P("MAXR"))) slot = &t.tmaxr;
    else if (eq_p(k, SC_P("HOME"))) slot = &t.thome;
    else if (eq_p(k, SC_P("VMAX"))) slot = &t.tvmax;
    else if (eq_p(k, SC_P("ACC"))) slot = &t.tacc;
  }
  if (!slot) { ack_p(c, f[0], false, SC_P("KEY")); return; }
  *slot = (int16_t)v;
  if (!sc_limits_valid(&t)) { ack_p(c, f[0], false, SC_P("RANGE")); return; }
  c->lim = t;
  char d[8];
  sc_snprintf(d, sizeof(d), SC_P("%c%s"), axis, k);
  ack(c, f[0], true, d);
  sc_emit_lim(c);
}

SC_NOINLINE static void handle_cal(sc_ctx *c, char **f, uint8_t n, uint32_t now_ms) {
  if (n != 2 || (strcmp(f[1], "0") && strcmp(f[1], "1"))) { err_p(c, SC_P("FMT"), now_ms); return; }
  if (f[1][0] == '1') {
    if (c->session && c->link_ok && c->alarm) { ack_p(c, f[0], false, SC_P("BUSY")); return; }
    c->cal_mode = true;
    c->fx = 0;
    c->session = false;
    c->token = TOK_ZERO;
    c->link_ok = false;
    c->lost = false;
    c->lost_homing = false;
    reset_session_view(c);
    hold_position(c);
    c->vlimit = SC_CAL_SPEED;
  } else if (c->cal_mode) {
    c->cal_mode = false;
    go_home(c, SC_CAL_SPEED);      /* the zone-aware escape brings it back safely */
  }
  ack(c, f[0], true, f[1]);
}

void sc_handle(sc_ctx *c, char *body, uint32_t now_ms) {
  char *f[SC_MAX_FIELDS];
  uint8_t n = split(body, f);
  if (n == 255) { err_p(c, SC_P("FMT"), now_ms); return; }
  const char *cmd = f[0];
  int32_t v;
  uint8_t r;
  char axis;
  if (eq_p(cmd, SC_P("S"))) { handle_s(c, f, n, now_ms); return; }
  if (eq_p(cmd, SC_P("HELLO"))) { handle_hello(c, f, n, now_ms); return; }
  if (eq_p(cmd, SC_P("SET"))) { handle_set(c, f, n, now_ms); return; }
  if (eq_p(cmd, SC_P("CAL"))) { handle_cal(c, f, n, now_ms); return; }
  if (eq_p(cmd, SC_P("PING"))) {
    r = (n == 2) ? parse_int(f[1], 0, 65535, &v) : PI_FMT;
    if (r) { range_err(c, r, now_ms); return; }
    char b[32];
    sc_snprintf(b, sizeof(b), SC_P("PONG,%ld,%lu"), (long)v, (unsigned long)now_ms);
    emit(c, b);
    return;
  }
  if (eq_p(cmd, SC_P("ENV"))) {
    uint32_t tok;
    if (n != 3 || !parse_token(f[1], &tok)) { err_p(c, SC_P("FMT"), now_ms); return; }
    if (!c->session || tok != c->token) { err_p(c, SC_P("TOKEN"), now_ms); return; }
    r = parse_int(f[2], -400, 1500, &v);
    if (r) { range_err(c, r, now_ms); return; }
    c->soc_dc = (int16_t)v;
    c->soc_ms = now_ms;
    c->soc_valid = true;
    return;
  }
  if (eq_p(cmd, SC_P("VOL"))) {
    r = (n == 2) ? parse_int(f[1], 0, 100, &v) : PI_FMT;
    if (r) { range_err(c, r, now_ms); return; }
    c->volume = (uint8_t)v;
    ack(c, cmd, true, f[1]);
    return;
  }
  if (eq_p(cmd, SC_P("GETLIM"))) {
    if (n != 1) { err_p(c, SC_P("FMT"), now_ms); return; }
    sc_emit_lim(c);
    return;
  }
  if (eq_p(cmd, SC_P("JOG"))) {
    if (n != 3 || !axis_arg(f[1], &axis)) { err_p(c, SC_P("FMT"), now_ms); return; }
    if (!c->cal_mode) { ack_p(c, cmd, false, SC_P("MODE")); return; }
    r = parse_int(f[2], 0, 1800, &v);
    if (r) { range_err(c, r, now_ms); return; }
    if (axis == 'P') c->pan.target = (float)v;
    else c->tilt.target = (float)v;
    c->vlimit = SC_CAL_SPEED;
    ack(c, cmd, true, f[2]);
    return;
  }
  if (eq_p(cmd, SC_P("SAVE")) || eq_p(cmd, SC_P("DEFAULTS"))) {
    if (n != 1) { err_p(c, SC_P("FMT"), now_ms); return; }
    if (!c->cal_mode) { ack_p(c, cmd, false, SC_P("MODE")); return; }
    if (cmd[0] == 'S') {
      if (!c->hooks.save || !c->hooks.save(c->hooks.user, &c->lim)) {
        ack_p(c, cmd, false, SC_P("IO"));
        return;
      }
      c->calibrated = true;
    } else {
      sc_limits_default(&c->lim);
      c->calibrated = false;
    }
    ack_p(c, cmd, true, SC_P("0"));
    sc_emit_lim(c);
    return;
  }
  if (eq_p(cmd, SC_P("FAN"))) {
    if (n != 3 || (strcmp(f[1], "A") && strcmp(f[1], "P"))) { err_p(c, SC_P("FMT"), now_ms); return; }
    r = parse_int(f[2], -1, 255, &v);
    if (r) { range_err(c, r, now_ms); return; }
    uint8_t i = f[1][0] == 'A' ? 0 : 1;
    c->fan_manual[i] = (int16_t)v;
    c->fan_manual_ms[i] = now_ms;
    ack(c, cmd, true, f[1]);
    return;
  }
  err_p(c, SC_P("CMD"), now_ms);
}

/* ------------------------------------------------------------ supervision */

void sc_tick(sc_ctx *c, uint32_t now_ms) {
  /* Signed: a frame stamped a moment AFTER now_ms must read as "fresh", not as a
   * 49-day-old frame (that wrap flashed "LINK AI PUTUS" on the rig, 26-10-2026). */
  if (c->session && !c->lost && (int32_t)(now_ms - c->last_s_ms) > (int32_t)SC_LINK_TIMEOUT_MS) {
    /* Brain went silent: stop the alarm at once, hold the view, home later. */
    c->link_ok = false;
    c->lost = true;
    c->lost_ms = now_ms;
    c->alarm = false;
    c->vox = false;
    c->fx = 0;
    hold_position(c);
    emit_p(c, SC_P("EVT,LINK,LOST"));
  }
  if (c->lost && !c->lost_homing && (uint32_t)(now_ms - c->lost_ms) >= SC_LOST_HOLD_MS) {
    c->lost_homing = true;
    go_home(c, SC_CAL_SPEED);
  }
  for (uint8_t i = 0; i < 2; ++i) {
    if (c->fan_manual[i] >= 0 && (int32_t)(now_ms - c->fan_manual_ms[i]) >= 60000L) c->fan_manual[i] = -1;
  }
  if (c->soc_valid && (int32_t)(now_ms - c->soc_ms) > 10000L) c->soc_valid = false;
}

/* ------------------------------------------------------------ motion */

static float fmin_(float a, float b) { return a < b ? a : b; }
static float fmax_(float a, float b) { return a > b ? a : b; }

/* Trapezoidal follower on the RAW pose: accel-limited, brakes in time, never crosses
 * the target. The servo never sees this raw pose directly: smooth_axis() below turns
 * it into an eased curve (see sc_motion_step). */
SC_NOINLINE static void axis_step(sc_axis *a, float target, float vmax, float acc, float dt) {
  float err = target - a->pos;
  float dv = acc * dt;
  a->acc = 0;
  if (fabsf(err) < 0.5f && fabsf(a->vel) <= dv) { a->pos = target; a->vel = 0; return; }
  float vdes = (err > 0 ? 1.0f : -1.0f) * fmin_(vmax, sqrtf(2.0f * acc * fabsf(err)));
  if (a->vel < vdes) a->vel = fmin_(a->vel + dv, vdes);
  else a->vel = fmax_(a->vel - dv, vdes);
  float np = a->pos + a->vel * dt;
  if ((err > 0 && a->vel > 0 && np >= target) || (err < 0 && a->vel < 0 && np <= target)) {
    a->pos = target;
    a->vel = 0;
    return;
  }
  a->pos = np;
}

/* Two cascaded exponential smoothers with the SAME coefficient on both axes.
 * Each stage is a weighted average of earlier poses, so the servo output is a convex
 * combination of raw poses that were all inside the (convex) safe zone: it stays in
 * the zone, never overshoots a monotonic move, and every start/stop becomes an
 * ease-in/ease-out curve (acceleration is continuous). */
SC_NOINLINE static void smooth_axis(sc_axis *a, float k) {
  a->f1 += k * (a->pos - a->f1);
  a->out += k * (a->f1 - a->out);
}

/* Keep an axis inside [lo, hi]. When it is already outside (boot pose, after CAL) it may
 * only move back toward the band, never further out. Empty band (lo > hi): hold. */
SC_NOINLINE static void bound_axis(sc_axis *a, float old, float lo, float hi) {
  float mn = fmin_(lo, old), mx = fmax_(hi, old);
  if (a->pos < mn || a->pos > mx) { a->pos = a->pos < mn ? mn : mx; a->vel = 0; }
}

/* Pan interval [lo, hi] inside the zone at this tilt. The zone is convex, so every
 * horizontal slice is one interval; lo > hi means tilt has to move first. */
static void pan_slice(const sc_limits *l, float tilt, float *lo, float *hi) {
  float a = l->pmin, b = l->pmax;
  /* where the floor meets this tilt */
  if (l->tmin1 < l->tmin0) a = seg(tilt, l->tmin1, l->tmin0, l->pmax, l->pmin);
  else if (l->tmin1 > l->tmin0) b = seg(tilt, l->tmin0, l->tmin1, l->pmin, l->pmax);
  /* where the ceiling meets this tilt (only right of home) */
  if (l->tmax > l->tmaxr) a = fmax_(a, seg(tilt, l->tmaxr, l->tmax, l->pmin, l->phome));
  *lo = a;
  *hi = b;
}

SC_NOINLINE static void zone_step(sc_ctx *c, float dt) {
  const sc_limits *l = &c->lim;
  float pacc = 10.0f * l->pacc, tacc = 10.0f * l->tacc;
  bool inside = sc_in_zone(l, c->pan.pos, c->tilt.pos);
  float pv = 10.0f * fmin_(c->vlimit, (float)l->pvmax);
  float tv = 10.0f * fmin_(c->vlimit, (float)l->tvmax);
  if (!inside) {   /* escape from outside the zone (after CAL) slowly */
    pv = fmin_(pv, 10.0f * SC_CAL_SPEED);
    tv = fmin_(tv, 10.0f * SC_CAL_SPEED);
  }
  /* Tilt first, between floor and ceiling at the CURRENT pan: "lift, then turn" at the
   * low corners and "lower, then turn" toward the hard-right top corner. */
  float lo = sc_tilt_floor_f(l, c->pan.pos), hi = sc_tilt_ceil_f(l, c->pan.pos);
  float old = c->tilt.pos;
  axis_step(&c->tilt, fmin_(fmax_(c->tilt.target, lo), hi), tv, tacc, dt);
  bound_axis(&c->tilt, old, lo, hi);
  /* Pan second, inside the slice at the NEW tilt. A target beyond the slice edge ("wall")
   * is replaced by the wall: pan brakes smoothly while tilt moves and the wall recedes,
   * instead of being stopped dead by bound_axis. */
  pan_slice(l, c->tilt.pos, &lo, &hi);
  old = c->pan.pos;
  axis_step(&c->pan, lo <= hi ? fmin_(fmax_(c->pan.target, lo), hi) : old, pv, pacc, dt);
  bound_axis(&c->pan, old, lo, hi);
}

/* ------------------------------------------------------------ gesture animations */

uint16_t sc_fx_duration(char fx) {
  switch (fx) {
    case 'N': return 1400;      /* nod: yes, yes */
    case 'H': return 1500;      /* shake: no, no */
    case 'C': return 1800;      /* curious robot: look around, tilt the head */
    case 'W': return 1300;      /* greet: small happy bob */
    default: return 0;
  }
}

bool sc_fx_start(sc_ctx *c, char fx, uint32_t now_ms) {
  if (!sc_fx_duration(fx) || c->cal_mode) return false;
  c->fx = fx;
  c->fx_started = fx;
  c->fx_ms = 0;
  c->fx_base_p = (int16_t)(c->pan.out + 0.5f);
  c->fx_base_t = (int16_t)(c->tilt.out + 0.5f);
  c->pan.pos = c->fx_base_p;
  c->tilt.pos = c->fx_base_t;
  c->fx_text = fx;
  c->fx_text_ms = now_ms;
  return true;
}

/* Smooth bumps so even the playful moves are eased. Polynomials instead of
 * sin/cos: the AVR trig library alone would not fit next to everything else.
 * bump(x) = 16 x^2 (1-x)^2 has zero slope at both ends, like a raised cosine. */
static float bump(float x) {      /* 0..1 -> 0..1..0 */
  if (x <= 0 || x >= 1) return 0;
  float y = x * (1.0f - x);
  return 16.0f * y * y;
}

/* Two eased swings right-left-right-left: alternating bumps, 0 at both ends. */
static float wave(float x, float cycles) {
  if (x <= 0 || x >= 1) return 0;
  float u = x * 2.0f * cycles;            /* half-swings */
  int k = (int)u;
  float b = bump(u - (float)k);
  return (k & 1) ? -b : b;
}

/* Offsets (dd) added to the base pose; the safe-zone clamp is applied afterwards. */
SC_NOINLINE static void fx_offset(char fx, float t, float *dp, float *dt) {
  *dp = *dt = 0;
  switch (fx) {
    case 'N': *dt = -110.0f * (bump(t / 0.5f) + bump((t - 0.5f) / 0.5f)); break;
    case 'H': *dp = 150.0f * wave(t, 2.0f); break;
    case 'C':
      *dp = 180.0f * bump(t / 0.45f) - 180.0f * bump((t - 0.45f) / 0.45f);
      *dt = -60.0f * bump((t - 0.2f) / 0.6f);
      break;
    case 'W':
      *dt = -45.0f * (bump(t / 0.33f) + bump((t - 0.33f) / 0.33f) + bump((t - 0.66f) / 0.34f));
      break;
    default: break;
  }
}

SC_NOINLINE static void fx_step(sc_ctx *c, float dt) {
  uint16_t dur = sc_fx_duration(c->fx);
  c->fx_ms += dt * 1000.0f;
  if (!dur || c->fx_ms >= dur) {
    c->fx = 0;
    c->pan.pos = c->fx_base_p;
    c->tilt.pos = c->fx_base_t;
    c->pan.vel = c->tilt.vel = 0;
    c->pan.acc = c->tilt.acc = 0;
    return;
  }
  float dp, dtt;
  fx_offset(c->fx, c->fx_ms / dur, &dp, &dtt);
  int16_t p = (int16_t)(c->fx_base_p + dp), t = (int16_t)(c->fx_base_t + dtt);
  bool clamped;
  sc_clamp(&c->lim, &p, &t, &clamped);
  /* The animation curve IS the motion profile: positions are already smooth. */
  c->pan.vel = ((float)p - c->pan.pos) / dt;
  c->tilt.vel = ((float)t - c->tilt.pos) / dt;
  c->pan.pos = p;
  c->tilt.pos = t;
}

void sc_motion_step(sc_ctx *c, float dt) {
  if (dt <= 0) return;
  if (dt > 0.1f) dt = 0.1f;
  if (c->fx && !c->cal_mode && sc_in_zone(&c->lim, c->pan.pos, c->tilt.pos)) {
    fx_step(c, dt);
  } else if (c->cal_mode) {
    /* Calibration explores beyond the soft zone on purpose, slowly. */
    float v = 10.0f * SC_CAL_SPEED;
    axis_step(&c->pan, c->pan.target, v, 10.0f * c->lim.pacc, dt);
    axis_step(&c->tilt, c->tilt.target, v, 10.0f * c->lim.tacc, dt);
  } else {
    zone_step(c, dt);
  }
  if (c->pan.pos < 0) c->pan.pos = 0;
  if (c->pan.pos > 1800) c->pan.pos = 1800;
  if (c->tilt.pos < 0) c->tilt.pos = 0;
  if (c->tilt.pos > 1800) c->tilt.pos = 1800;
  float k = dt / (SC_SMOOTH_TAU + dt);
  smooth_axis(&c->pan, k);
  smooth_axis(&c->tilt, k);
  c->moving = fabsf(c->pan.vel) > 1.0f || fabsf(c->tilt.vel) > 1.0f ||
              fabsf(c->pan.target - c->pan.pos) >= 0.5f || fabsf(c->tilt.target - c->tilt.pos) >= 0.5f ||
              fabsf(c->pan.out - c->pan.pos) >= 0.5f || fabsf(c->tilt.out - c->tilt.pos) >= 0.5f;
}

/* ------------------------------------------------------------ fans */

uint8_t sc_fan_duty(sc_ctx *c, uint8_t idx, int16_t temp_dc, uint32_t now_ms) {
  (void)now_ms;
  if (idx > 1) return 0;
  if (c->fan_manual[idx] >= 0) return (uint8_t)c->fan_manual[idx];
  int16_t t = temp_dc;
  if (idx == 1 && c->soc_valid) {
    /* SoC die runs ~10 C above a heatsink probe: compare on the probe scale. */
    int16_t soc = (int16_t)(c->soc_dc - 100);
    if (t == SC_TEMP_NA || soc > t) t = soc;
  }
  /* No DS18B20 fitted yet (26-10-2026: on order) and no SoC report: fan OFF. A sensor
   * plugged in later is found by the 2 s presence probe and takes over automatically. */
  if (t == SC_TEMP_NA) { c->fan_on[idx] = false; return 0; }
  if (c->fan_on[idx]) { if (t < 340) c->fan_on[idx] = false; }
  else if (t >= 380) c->fan_on[idx] = true;
  if (!c->fan_on[idx]) return 0;
  if (t >= 550) return 255;
  int32_t duty = 90 + (int32_t)(t - 340) * (255 - 90) / (550 - 340);
  if (duty < 90) duty = 90;
  return (uint8_t)duty;
}

/* ------------------------------------------------------------ display */

static void pad16(char *row) {
  size_t n = strlen(row);
  while (n < 16) row[n++] = ' ';
  row[16] = '\0';
}

static const char *item_word(char s) {
  return s == 'P' ? "OK" : s == 'A' ? "NO" : s == 'U' ? "??" : "--";
}

static void item_leds(const sc_ctx *c, bool fast, bool tick, uint8_t *leds) {
  static const uint8_t bit[3] = {SC_LED_HELM, SC_LED_ROMPI, SC_LED_SEPATU};
  for (uint8_t i = 0; i < 3; ++i) {
    char s = c->items[i];
    if (s == 'P' || (s == 'A' && fast) || (s == 'U' && tick)) *leds |= bit[i];
  }
}

/* Text never contains per-frame values (no blinking text, no live counters), so the
 * candidate only changes when the situation changes. Blinking stays on the LEDs. */
void sc_display(const sc_ctx *c, uint32_t now_ms, char row0[17], char row1[17],
                uint8_t *leds, uint8_t *level) {
  uint32_t up = now_ms - c->boot_ms;
  bool fast = ((now_ms / 125) & 1) != 0;      /* 4 Hz blink */
  bool slow = ((now_ms / 500) & 1) != 0;      /* 1 Hz blink */
  bool tick = (now_ms % 1500) < 100;          /* short flash every 1.5 s */
  *leds = 0;
  *level = SC_LCD_NORMAL;
  row0[0] = row1[0] = '\0';
  if (up < SC_BOOT_SCREEN_MS) {
    sc_snprintf(row0, 17, SC_P("APD SENTINEL 3.2"));
    sc_snprintf(row1, 17, SC_P("Tes lampu..."));
    *leds = (uint8_t)(1u << ((up / 300) % 4));  /* sweep red, green, yellow, alarm */
    *level = SC_LCD_URGENT;
  } else if (c->cal_mode) {
    sc_snprintf(row0, 17, SC_P("MODE KALIBRASI"));
    sc_snprintf(row1, 17, SC_P("P%4d  T%4d"), round_dd(c->pan.target), round_dd(c->tilt.target));
    *level = SC_LCD_URGENT;
  } else if (c->lost) {
    sc_snprintf(row0, 17, SC_P("LINK AI PUTUS!"));
    if (c->lost_homing) sc_snprintf(row1, 17, SC_P("Kembali ke home"));
    else sc_snprintf(row1, 17, SC_P("Servo ditahan"));
    if (slow) *leds = SC_LED_HELM | SC_LED_ROMPI | SC_LED_SEPATU;
    *level = SC_LCD_URGENT;
  } else if (!c->session || !c->link_ok) {
    sc_snprintf(row0, 17, SC_P("APD SENTINEL"));
    sc_snprintf(row1, 17, SC_P("Menunggu AI..."));
  } else if (c->alarm) {
    static const char names[3][4] = {"HLM", "RMP", "SPT"};
    char miss[17] = "";
    for (uint8_t i = 0; i < 3; ++i) {
      if (c->items[i] == 'A') {
        if (miss[0]) strcat(miss, " ");
        strcat(miss, names[i]);
      }
    }
    if (c->items[3] == 'A') strcat(miss, miss[0] ? " SRT" : "SRT");
    sc_snprintf(row0, 17, SC_P("!! ALARM APD !!"));
    sc_snprintf(row1, 17, SC_P("Krg:%s"), miss);
    item_leds(c, fast, tick, leds);
    *level = SC_LCD_URGENT;
  } else if (c->fx_text && (int32_t)(now_ms - c->fx_text_ms) < (int32_t)SC_LCD_HOLD_MS) {
    switch (c->fx_text) {
      case 'N':
        sc_snprintf(row0, 17, SC_P("Jempol diterima"));
        sc_snprintf(row1, 17, SC_P("Iya! Mantap :)"));
        break;
      case 'H':
        sc_snprintf(row0, 17, SC_P("Tanpa sarung"));
        sc_snprintf(row1, 17, SC_P("tangan! Tidak."));
        break;
      case 'W':
        sc_snprintf(row0, 17, SC_P("Halo juga! :)"));
        sc_snprintf(row1, 17, SC_P("Hati-hati ya"));
        break;
      default:
        sc_snprintf(row0, 17, SC_P("Hmm... mencari"));
        sc_snprintf(row1, 17, SC_P("orang di area"));
        break;
    }
    if (c->mode == 'T' || c->mode == 'G' || c->mode == 'V') item_leds(c, fast, tick, leds);
    *level = SC_LCD_EVENT;
  } else {
    switch (c->mode) {
      case 'I':
        sc_snprintf(row0, 17, SC_P("Memantau area"));
        sc_snprintf(row1, 17, SC_P("Tidak ada orang"));
        break;
      case 'P':
        sc_snprintf(row0, 17, SC_P("Patroli area..."));
        sc_snprintf(row1, 17, SC_P("Mencari orang"));
        break;
      case 'A':
        sc_snprintf(row0, 17, SC_P("Orang terdeteksi"));
        sc_snprintf(row1, 17, SC_P("Mengunci..."));
        break;
      case 'T':
        sc_snprintf(row0, 17, SC_P("Cek APD  ID:%u"), (unsigned)c->trk);
        break;
      case 'G':
        sc_snprintf(row0, 17, SC_P("Grup %u orang"), (unsigned)c->ppl);
        break;
      case 'V':
        sc_snprintf(row0, 17, SC_P("APD KURANG ID:%u"), (unsigned)c->trk);
        break;
      case 'S':
        sc_snprintf(row0, 17, SC_P("Mencari ID:%u"), (unsigned)c->trk);
        sc_snprintf(row1, 17, SC_P("Target hilang"));
        break;
      default:
        sc_snprintf(row0, 17, SC_P("GANGGUAN KAMERA"));
        sc_snprintf(row1, 17, SC_P("Cek kamera / AI"));
        if (slow) *leds = SC_LED_HELM | SC_LED_ROMPI | SC_LED_SEPATU;
        *level = SC_LCD_URGENT;
        break;
    }
    if (c->mode == 'T' || c->mode == 'G' || c->mode == 'V') {
      sc_snprintf(row1, 17, SC_P("H:%s R:%s S:%s"), item_word(c->items[0]),
                  item_word(c->items[1]), item_word(c->items[2]));
      item_leds(c, fast, tick, leds);
    }
  }
  pad16(row0);
  pad16(row1);
}

bool sc_lcd_update(sc_ctx *c, uint32_t now_ms, const char row0[17], const char row1[17], uint8_t level) {
  bool same = c->lcd_init && !strcmp(c->lcd_rows[0], row0) && !strcmp(c->lcd_rows[1], row1);
  if (same) {
    c->lcd_level = level;
    return false;
  }
  /* Urgent text and event text replace anything at once. Normal text waits until the
   * current screen has been shown for SC_LCD_HOLD_MS, so status changes never spam. */
  bool allowed = !c->lcd_init || level >= SC_LCD_EVENT ||
                 c->lcd_level == SC_LCD_URGENT ||
                 (uint32_t)(now_ms - c->lcd_changed_ms) >= SC_LCD_HOLD_MS;
  if (!allowed) return false;
  memcpy(c->lcd_rows[0], row0, 17);
  memcpy(c->lcd_rows[1], row1, 17);
  c->lcd_level = level;
  c->lcd_changed_ms = now_ms;
  c->lcd_init = true;
  return true;
}
