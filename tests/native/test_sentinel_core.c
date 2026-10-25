/* Host test of the exact firmware core (arduino/apd_sentinel/sentinel_core.c). */
#include "../../arduino/apd_sentinel/sentinel_core.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;
#define CHECK(x) do { if (!(x)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #x); ++failures; } } while (0)

static char out[64][128];
static int nout = 0;
static void cap(void *u, const char *b) {
  (void)u;
  if (nout < 64) { strncpy(out[nout], b, 127); out[nout][127] = 0; }
  ++nout;
}
static sc_limits saved;
static int have_saved = 0;
static bool save_hook(void *u, const sc_limits *l) { (void)u; saved = *l; have_saved = 1; return true; }
static bool load_hook(void *u, sc_limits *l) { (void)u; if (!have_saved) return false; *l = saved; return true; }
static int has(const char *prefix) {
  for (int i = 0; i < nout && i < 64; ++i) if (!strncmp(out[i], prefix, strlen(prefix))) return 1;
  return 0;
}
static void clear(void) { nout = 0; }

static int feed(sc_framer *f, const char *wire, uint32_t t, char *body) {
  int last = SC_NONE;
  for (const char *p = wire; *p; ++p) {
    int r = sc_framer_feed(f, *p, t, body);
    if (r != SC_NONE) last = r;
  }
  return last;
}

static void send(sc_ctx *c, const char *body, uint32_t t) {
  char b[128];
  strcpy(b, body);
  sc_handle(c, b, t);
}

static void test_framing(void) {
  CHECK(sc_crc8("HELLO,1A2B3C4D", 14) == 0xC8);   /* golden vectors shared with Python */
  CHECK(sc_crc8("PING,7", 6) == 0x43);
  CHECK(sc_crc8("SAVE", 4) == 0x85);
  sc_framer f;
  char body[SC_BODY_MAX + 1];
  sc_framer_init(&f);
  CHECK(feed(&f, "$PING,7*43\n", 0, body) == SC_FRAME && !strcmp(body, "PING,7"));
  CHECK(feed(&f, "$PING,7*43\r\n", 0, body) == SC_FRAME);
  CHECK(feed(&f, "$PING,7*44\n", 0, body) == SC_BAD_CRC);
  CHECK(feed(&f, "$PING,7*4c\n", 0, body) == SC_BAD_FORMAT);        /* lowercase hex */
  CHECK(feed(&f, "$PI$PING,7*43\n", 0, body) == SC_FRAME);          /* '$' restarts */
  CHECK(feed(&f, "#HELP\n", 0, body) == SC_CONSOLE && !strcmp(body, "HELP"));
  CHECK(feed(&f, "garbage\n", 0, body) == SC_NONE);
  char longf[200];
  memset(longf, 'A', 150);
  longf[0] = '$';
  strcpy(longf + 150, "*00\n");
  CHECK(feed(&f, longf, 0, body) == SC_OVERFLOW);
  sc_framer_feed(&f, '$', 0, body);
  sc_framer_feed(&f, 'P', 10, body);
  CHECK(feed(&f, "ING,7*43\n", 500, body) == SC_NONE);              /* inter-byte timeout */
}

static void test_zone(void) {
  sc_limits l;
  sc_limits_default(&l);
  CHECK(sc_limits_valid(&l));
  CHECK(sc_tilt_floor_i(&l, 0) == 1450 && sc_tilt_floor_i(&l, 1450) == 1000);
  CHECK(sc_tilt_floor_i(&l, 900) == 1171);                          /* 1170.69 rounded up */
  for (int p = 0; p <= 1450; ++p)
    CHECK(sc_tilt_floor_f(&l, (float)p) <= sc_tilt_floor_i(&l, (int16_t)p) + 0.001f);
  int16_t p = 1600, t = 500;
  bool cl;
  sc_clamp(&l, &p, &t, &cl);
  CHECK(cl && p == 1450 && t == 1000);
  p = 900; t = 1800;
  sc_clamp(&l, &p, &t, &cl);
  CHECK(!cl);
  CHECK(sc_dd_to_us(0) == 544 && sc_dd_to_us(1800) == 2400 && sc_dd_to_us(900) == 1472);
}

static void test_session(void) {
  sc_ctx c;
  sc_hooks h = {cap, save_hook, load_hook, 0};
  clear();
  sc_init(&c, &h, 0);
  CHECK(has("READY,SENTINEL,3.1.0,00000000,0") && has("LIM,0,900,1450,1450,1000,1250,1800,"));
  CHECK(c.pan.pos == 900 && c.tilt.pos == 1250);
  clear(); send(&c, "S,1A2B3C4D,1,T,900,1700,60,PPP,0,1,0,3", 10);
  CHECK(has("ERR,TOKEN"));
  clear(); send(&c, "HELLO,1A2B3C4D", 20);
  CHECK(has("READY,SENTINEL,3.1.0,1A2B3C4D,0") && c.session);
  clear(); send(&c, "S,1A2B3C4D,1,T,600,1700,60,PAU,0,1,0,3", 30);
  CHECK(nout == 1 && has("EVT,LINK,OK") && c.link_ok && c.trk == 3 && !strncmp(c.items, "PAU", 3));
  clear(); send(&c, "S,1A2B3C4D,1,T,600,1700,60,PAU,0,1,0,3", 40);
  CHECK(has("ERR,SEQ"));
  clear(); send(&c, "S,1A2B3C4D,2,T,600,1700,60,PAU,1,1,0,3", 50);
  CHECK(has("ERR,RANGE"));                                          /* alarm without V */
  clear(); send(&c, "S,1A2B3C4D,3,P,600,1700,60,---,0,0,0,0", 55);
  CHECK(nout == 0 && c.mode == 'P');
  clear(); send(&c, "S,1A2B3C4D,3,X,600,1700,60,PAU,0,1,0,3", 60);
  CHECK(has("ERR,FMT"));
  clear(); send(&c, "S,1A2B3C4D,5,V,0,1000,60,AAA,1,1,1,3", 70);
  CHECK(nout == 0 && c.alarm && c.clamped && c.pan.target == 0 && c.tilt.target == 1450);
  c.last_seq = 65535;
  clear(); send(&c, "S,1A2B3C4D,1,T,900,1800,60,PPP,0,1,0,3", 80);  /* sequence wrap */
  CHECK(nout == 0);

  /* link loss: alarm off at once, hold, then home after 5 s */
  sc_tick(&c, 80 + 1400);
  CHECK(c.link_ok);
  clear(); sc_tick(&c, 80 + 1600);
  CHECK(!c.link_ok && !c.alarm && has("EVT,LINK,LOST"));
  sc_tick(&c, 80 + 1600 + 5100);
  CHECK(c.lost_homing && c.pan.target == 900 && c.tilt.target == 1250);

  /* calibration */
  clear(); send(&c, "SET,P,MIN,100", 9000);   CHECK(has("ACK,SET,ERR,MODE"));
  clear(); send(&c, "CAL,1", 9000);           CHECK(has("ACK,CAL,OK,1") && c.cal_mode && !c.session);
  clear(); send(&c, "SET,P,MIN,1500", 9000);  CHECK(has("ACK,SET,ERR,RANGE") && c.lim.pmin == 0);
  clear(); send(&c, "SET,T,MIN1,1050", 9000); CHECK(has("ACK,SET,OK,TMIN1") && c.lim.tmin1 == 1050);
  clear(); send(&c, "SET,T,FOO,1", 9000);     CHECK(has("ACK,SET,ERR,KEY"));
  clear(); send(&c, "JOG,P,200", 9000);       CHECK(has("ACK,JOG,OK,200") && c.pan.target == 200);
  clear(); send(&c, "SAVE", 9000);            CHECK(has("ACK,SAVE,OK,0") && c.calibrated && saved.tmin1 == 1050);
  clear(); send(&c, "DEFAULTS", 9000);        CHECK(c.lim.tmin1 == 1000 && !c.calibrated);
  clear(); send(&c, "LOAD", 9000);            CHECK(has("ERR,CMD"));          /* removed: reboot loads EEPROM */
  clear(); send(&c, "CAL,0", 9000);           CHECK(!c.cal_mode && c.pan.target == 900);
  clear(); send(&c, "NOPE", 9000);            CHECK(has("ERR,CMD"));
  clear(); send(&c, "PING,7", 9000);          CHECK(has("PONG,7,9000"));
  clear();
  for (int i = 0; i < 10; ++i) send(&c, "NOPE", 20000);
  CHECK(nout == 4);                                                 /* ERR rate limit */
}

static void test_motion(void) {
  srand(12345);
  int moves = 0, total = 0;
  int failures_before = failures;
  for (int trial = 0; trial < 400 && failures == failures_before; ++trial) {
    sc_ctx m;
    sc_init(&m, 0, 0);
    for (int k = 0; k < 6; ++k) {
      int16_t p = (int16_t)(rand() % 1801), t = (int16_t)(rand() % 1801);
      bool cl;
      sc_clamp(&m.lim, &p, &t, &cl);
      m.pan.target = p;
      m.tilt.target = t;
      m.vlimit = (float)(10 + rand() % 590);
      for (int s = 0; s < 600; ++s) {
        sc_motion_step(&m, 0.02f);
        if (!sc_in_zone(&m.lim, m.pan.pos, m.tilt.pos) || !sc_in_zone(&m.lim, m.pan.out, m.tilt.out)) {
          printf("ZONE VIOLATION trial %d pan %.2f tilt %.2f floor %.2f\n", trial,
                 (double)m.pan.pos, (double)m.tilt.pos, (double)sc_tilt_floor_f(&m.lim, m.pan.pos));
          ++failures;
          return;
        }
        if (fabsf(m.pan.vel) > 10.0f * m.lim.pvmax + 1 || fabsf(m.tilt.vel) > 10.0f * m.lim.tvmax + 1) {
          printf("SPEED VIOLATION\n");
          ++failures;
          return;
        }
      }
      ++total;
      if (fabsf(m.pan.out - p) < 0.6f && fabsf(m.tilt.out - t) < 0.6f) ++moves;
    }
  }
  printf("random moves reached target: %d / %d\n", moves, total);
  CHECK(moves == total);

  /* "lift, then turn": low-left -> low-right must raise tilt before panning */
  sc_ctx m;
  sc_init(&m, 0, 0);
  m.pan.pos = 1450; m.tilt.pos = 1000;
  m.pan.target = 0; m.tilt.target = 1450; m.vlimit = 120;
  float min_margin = 1e9f;
  for (int s = 0; s < 1000; ++s) {
    sc_motion_step(&m, 0.02f);
    float mg = m.tilt.out - sc_tilt_floor_f(&m.lim, m.pan.out);
    if (mg < min_margin) min_margin = mg;
  }
  CHECK(min_margin > -0.02f && fabsf(m.pan.out) < 0.6f && fabsf(m.tilt.out - 1450) < 0.6f);

  /* escape from outside the zone (after CAL) is slow and ends inside */
  sc_init(&m, 0, 0);
  m.pan.pos = m.pan.f1 = m.pan.out = 1450;
  m.tilt.pos = m.tilt.f1 = m.tilt.out = 700;
  m.pan.target = 900; m.tilt.target = 1800; m.vlimit = 600;
  int outside_steps = 0;
  for (int s = 0; s < 2000; ++s) {
    bool was_outside = !sc_in_zone(&m.lim, m.pan.pos, m.tilt.pos);
    sc_motion_step(&m, 0.02f);
    /* Slow escape applies only while still outside; inside, normal speed is fine. */
    if (was_outside) {
      ++outside_steps;
      CHECK(fabsf(m.pan.vel) <= 301 && fabsf(m.tilt.vel) <= 301);
    }
  }
  CHECK(outside_steps > 0);
  CHECK(sc_in_zone(&m.lim, m.pan.pos, m.tilt.pos) && fabsf(m.pan.pos - 900) < 0.6f);
}

static void test_display_and_fans(void) {
  sc_ctx d;
  char r0[17], r1[17];
  uint8_t leds, level;
  sc_init(&d, 0, 0);
  d.session = d.link_ok = true;
  d.mode = 'V'; d.alarm = true; d.trk = 5;
  strcpy(d.items, "APA-");
  sc_display(&d, 10125, r0, r1, &leds, &level);
  CHECK(strlen(r0) == 16 && strlen(r1) == 16 && !strncmp(r1, "Krg:HLM SPT", 11));
  CHECK(level == SC_LCD_URGENT && !strncmp(r0, "!! ALARM APD !!", 15));
  CHECK(leds & SC_LED_ROMPI);
  /* alarm text is steady (no blinking text): same at an "off" blink phase */
  char s0[17], s1[17];
  sc_display(&d, 10000, s0, s1, &leds, &level);
  CHECK(!strcmp(s0, r0) && !strcmp(s1, r1));

  /* LCD pacing: normal text changes at most every 3 s; urgent overrides at once */
  sc_ctx L;
  sc_init(&L, 0, 0);
  L.session = L.link_ok = true;
  L.mode = 'I';
  sc_display(&L, 5000, r0, r1, &leds, &level);
  CHECK(sc_lcd_update(&L, 5000, r0, r1, level));                    /* first commit */
  L.mode = 'A';
  sc_display(&L, 5200, r0, r1, &leds, &level);
  CHECK(!sc_lcd_update(&L, 5200, r0, r1, level));                   /* held (0.2 s) */
  CHECK(!strncmp(L.lcd_rows[0], "Memantau area", 13));
  sc_display(&L, 8100, r0, r1, &leds, &level);
  CHECK(sc_lcd_update(&L, 8100, r0, r1, level));                    /* after 3 s */
  CHECK(!strncmp(L.lcd_rows[0], "Orang terdeteksi", 16));
  L.mode = 'T';
  sc_display(&L, 8300, r0, r1, &leds, &level);
  CHECK(!sc_lcd_update(&L, 8300, r0, r1, level));
  L.alarm = true; L.mode = 'V';
  sc_display(&L, 8400, r0, r1, &leds, &level);
  CHECK(sc_lcd_update(&L, 8400, r0, r1, level));                    /* urgent: at once */
  L.alarm = false; L.mode = 'T';
  sc_display(&L, 8500, r0, r1, &leds, &level);
  CHECK(sc_lcd_update(&L, 8500, r0, r1, level));                    /* leaving urgent */
  int changes = 0;
  for (uint32_t t = 8600; t < 20600; t += 100) {                    /* flicker every 0.1 s */
    L.mode = ((t / 100) & 1) ? 'T' : 'A';
    sc_display(&L, t, r0, r1, &leds, &level);
    changes += sc_lcd_update(&L, t, r0, r1, level);
  }
  CHECK(changes <= 4);                                              /* 12 s -> <= 4 changes */
  sc_ctx z;
  sc_init(&z, 0, 0);
  CHECK(sc_fan_duty(&z, 0, SC_TEMP_NA, 0) == 160);
  CHECK(sc_fan_duty(&z, 0, 300, 0) == 0);
  CHECK(sc_fan_duty(&z, 0, 400, 0) > 90);
  CHECK(sc_fan_duty(&z, 0, 360, 0) > 0);     /* hysteresis keeps it on */
  CHECK(sc_fan_duty(&z, 0, 330, 0) == 0);
  CHECK(sc_fan_duty(&z, 0, 600, 0) == 255);
}

static void test_v11_and_fx(void) {
  sc_ctx c;
  sc_hooks h = {cap, save_hook, load_hook, 0};
  clear();
  sc_init(&c, &h, 0);
  send(&c, "HELLO,1A2B3C4D", 10);
  /* SLP/1.1: items with glove, fx, fx_id, vox */
  clear(); send(&c, "S,1A2B3C4D,1,T,900,1500,60,PPPA,0,1,0,3,N,7,1", 20);
  CHECK(nout == 1 && has("EVT,LINK,OK") && c.items[3] == 'A' && c.vox && c.fx == 'N');
  CHECK(c.fx_started == 'N');
  c.fx_started = 0;
  /* same fx_id repeated at 10 Hz does not restart the animation */
  clear(); send(&c, "S,1A2B3C4D,2,T,900,1500,60,PPPA,0,1,0,3,N,7,1", 120);
  CHECK(nout == 0 && c.fx_started == 0);
  /* SLP/1.0 frames are still accepted */
  clear(); send(&c, "S,1A2B3C4D,3,T,900,1500,60,PPP,0,1,0,3", 220);
  CHECK(nout == 0 && c.items[3] == '-' && c.vox);      /* SLP/1.0: sound allowed */
  clear(); send(&c, "S,1A2B3C4D,4,T,900,1500,60,PPPA,0,1,0,3,X,7,1", 320);
  CHECK(has("ERR,FMT"));
  clear(); send(&c, "S,1A2B3C4D,5,T,900,1500,60,PPP,0,1,0,3,N,7,1", 420);
  CHECK(has("ERR,FMT"));                                            /* 15 fields need 4 items */

  /* every animation stays inside the safe zone, even started at the zone corners */
  const char fxs[4] = {'N', 'H', 'C', 'W'};
  const int16_t poses[5][2] = {{900, 1800}, {0, 1450}, {1450, 1000}, {0, 1800}, {700, 1300}};
  for (int f = 0; f < 4; ++f) {
    for (int k = 0; k < 5; ++k) {
      sc_ctx m;
      sc_init(&m, 0, 0);
      m.pan.pos = m.pan.target = m.pan.f1 = m.pan.out = poses[k][0];
      m.tilt.pos = m.tilt.target = m.tilt.f1 = m.tilt.out = poses[k][1];
      CHECK(sc_fx_start(&m, fxs[f], 0));
      float moved = 0;
      for (int step = 0; step < 150 && m.fx; ++step) {
        float p0 = m.pan.pos, t0 = m.tilt.pos;
        sc_motion_step(&m, 0.02f);
        moved += fabsf(m.pan.pos - p0) + fabsf(m.tilt.pos - t0);
        if (!sc_in_zone(&m.lim, m.pan.out, m.tilt.out)) {
          printf("FX ZONE VIOLATION fx %c pose %d\n", fxs[f], k);
          ++failures;
          break;
        }
      }
      CHECK(m.fx == 0);                                             /* finished */
      if (k == 0 || k == 4) CHECK(moved > 50);                      /* visible motion */
      /* returns to the start pose (eased curves end at 0 offset) */
      CHECK(fabsf(m.pan.pos - poses[k][0]) < 2.0f && fabsf(m.tilt.pos - poses[k][1]) < 2.0f);
    }
  }

  /* Eased output: the servo pulse sequence has no velocity jumps (no "patah-patah"). */
  const int16_t moves[4][2] = {{200, 1800}, {1450, 1000}, {0, 1450}, {900, 1250}};
  float worst_jump = 0;
  for (int k = 0; k < 4; ++k) {
    sc_ctx m;
    sc_init(&m, 0, 0);
    if (k == 2) { m.pan.pos = m.pan.f1 = m.pan.out = 1450; m.tilt.pos = m.tilt.f1 = m.tilt.out = 1000; }
    int16_t p = moves[k][0], t = moves[k][1];
    bool cl;
    sc_clamp(&m.lim, &p, &t, &cl);
    m.pan.target = p; m.tilt.target = t; m.vlimit = 120;
    float pp = m.pan.out, tp = m.tilt.out, pv = 0, tv = 0;
    for (int step = 0; step < 600; ++step) {
      sc_motion_step(&m, 0.02f);
      float v1 = (m.pan.out - pp) / 0.02f, v2 = (m.tilt.out - tp) / 0.02f;
      float jump = fmaxf(fabsf(v1 - pv), fabsf(v2 - tv));   /* dd/s change per 20 ms frame */
      if (jump > worst_jump) worst_jump = jump;
      pp = m.pan.out; tp = m.tilt.out; pv = v1; tv = v2;
    }
    CHECK(fabsf(m.pan.out - p) < 0.6f && fabsf(m.tilt.out - t) < 0.6f);
  }
  printf("Eased output: worst speed change %.0f dd/s per frame (raw trapezoid stop = 1200)\n",
         (double)worst_jump);
  CHECK(worst_jump < 400.0f);

  /* VOL command */
  sc_ctx v;
  clear();
  sc_init(&v, &h, 0);
  CHECK(v.volume == 50);
  clear(); send(&v, "VOL,30", 10); CHECK(has("ACK,VOL,OK,30") && v.volume == 30);
  clear(); send(&v, "VOL,101", 10); CHECK(has("ERR,RANGE") && v.volume == 30);
}

int main(void) {
  test_framing();
  test_v11_and_fx();
  test_zone();
  test_session();
  test_motion();
  test_display_and_fans();
  if (failures) printf("FAILED: %d\n", failures);
  else printf("ALL SENTINEL CORE TESTS PASSED\n");
  return failures ? 1 : 0;
}
