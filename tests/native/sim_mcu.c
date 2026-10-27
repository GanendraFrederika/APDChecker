/* Software MCU: the exact firmware core (sentinel_core.c) behind a byte-stream API,
 * scheduled like apd_sentinel.ino (motion 50 Hz, telemetry 20 Hz, display 10 Hz with
 * the LCD mirror, fans 1 Hz). scripts/sentinel_hil.py --sim drives the real brain and
 * link code against it, so the whole stack is testable without servos or USB power. */
#include "../../arduino/apd_sentinel/sentinel_core.h"
#include <stdio.h>
#include <string.h>

#ifdef _WIN32
#define SIM_API __declspec(dllexport)
#else
#define SIM_API __attribute__((visibility("default")))
#endif

static sc_ctx core;
static sc_framer framer;
static char body[SC_BODY_MAX + 1];
static char outbuf[65536];
static int outlen;
static uint32_t last_motion, last_tele, last_disp, last_fan, lcd_echo;
static sc_hw hw;
static sc_limits eeprom;
static int have_eeprom;

static void put(const char *b) {
  size_t len = strlen(b);
  if (outlen + (int)len + 6 >= (int)sizeof(outbuf)) return;     /* host stopped reading */
  outlen += snprintf(outbuf + outlen, sizeof(outbuf) - (size_t)outlen, "$%s*%02X\n", b,
                     sc_crc8(b, (uint8_t)len));
}
static void emit(void *u, const char *b) { (void)u; put(b); }
static bool save(void *u, const sc_limits *l) { (void)u; eeprom = *l; have_eeprom = 1; return true; }
static bool load(void *u, sc_limits *l) { (void)u; if (!have_eeprom) return false; *l = eeprom; return true; }

/* Power-on / port-open reset. temps in deci-C or SC_TEMP_NA. */
SIM_API void sim_boot(uint32_t now_ms, int temp_a, int temp_p) {
  sc_hooks h = {emit, save, load, 0};
  outlen = 0;
  sc_framer_init(&framer);
  sc_init(&core, &h, now_ms);
  last_motion = last_tele = last_disp = last_fan = lcd_echo = now_ms;
  memset(&hw, 0, sizeof(hw));
  hw.temp_a = (int16_t)temp_a;
  hw.temp_p = (int16_t)temp_p;
  hw.fan_a = hw.fan_p = 0;
  hw.vcc_mv = 5000;
  hw.lcd_ok = true;
  put("EVT,BOOT,00");
}

SIM_API int sim_io(uint32_t now_ms, const char *in, int n, char *out, int cap) {
  for (int i = 0; i < n; ++i) {
    int r = sc_framer_feed(&framer, in[i], now_ms, body);
    if (r == SC_FRAME) sc_handle(&core, body, now_ms);
    else if (r < 0) sc_frame_error(&core, r, now_ms);
  }
  sc_tick(&core, now_ms);
  for (int k = 0; (uint32_t)(now_ms - last_motion) >= 20 && k < 50; ++k) {
    last_motion += 20;
    sc_motion_step(&core, 0.02f);
  }
  if ((uint32_t)(now_ms - last_motion) >= 20) last_motion = now_ms;   /* host stalled: skip */
  bool alarm = core.alarm && core.link_ok && !core.cal_mode && core.vox;
  hw.sounding = alarm;
  hw.relay = alarm || core.fx_started;
  core.fx_started = 0;
  if ((uint32_t)(now_ms - last_fan) >= 1000) {
    last_fan = now_ms;
    hw.fan_a = sc_fan_duty(&core, 0, hw.temp_a, now_ms);
    hw.fan_p = sc_fan_duty(&core, 1, hw.temp_p, now_ms);
  }
  if ((uint32_t)(now_ms - last_disp) >= 100) {
    last_disp = now_ms;
    char r0[17], r1[17];
    uint8_t leds, level;
    sc_display(&core, now_ms, r0, r1, &leds, &level);
    bool changed = sc_lcd_update(&core, now_ms, r0, r1, level);
    if (changed || (uint32_t)(now_ms - lcd_echo) >= 2000) {
      char b[38];
      lcd_echo = now_ms;
      memcpy(b, "LCD,", 4);
      memcpy(b + 4, core.lcd_rows[0], 16);
      b[20] = '|';
      memcpy(b + 21, core.lcd_rows[1], 16);
      b[37] = '\0';
      put(b);
    }
  }
  if ((uint32_t)(now_ms - last_tele) >= 50) {
    last_tele = now_ms;
    sc_emit_telemetry(&core, now_ms, &hw);
  }
  int k = outlen < cap ? outlen : cap;
  memcpy(out, outbuf, (size_t)k);
  memmove(outbuf, outbuf + k, (size_t)(outlen - k));
  outlen -= k;
  return k;
}
