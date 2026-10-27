#ifndef SENTINEL_CORE_H
#define SENTINEL_CORE_H
/* APD Sentinel MCU core: SLP/1.1 framing, session, safe zone, eased motion,
 * gesture animations, display/fan policy. Pure C99, no Arduino headers: the PC
 * test suite compiles this exact file. Contract: docs/sentinel/PROTOCOL.md.
 * Angles are servo deci-degrees (dd) 0..1800, i.e. Servo.write() degrees x10. */
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define SC_VERSION "3.2.0"
#define SC_BODY_MAX 80
#define SC_MAX_FIELDS 16
#define SC_LINK_TIMEOUT_MS 1500UL
#define SC_LOST_HOLD_MS 5000UL
#define SC_INTERBYTE_MS 100UL
#define SC_BOOT_SCREEN_MS 2500UL
#define SC_LCD_HOLD_MS 3000UL      /* normal LCD text changes at most once per 3 s */
#define SC_CAL_SPEED 30            /* deg/s for JOG, zone escape and lost-link homing */
#define SC_SMOOTH_TAU 0.07f        /* s per smoothing stage (2 stages ~ 0.14 s of easing) */
#define SC_TEMP_NA (-32768)

enum { SC_NONE = 0, SC_FRAME = 1, SC_CONSOLE = 2,
       SC_BAD_CRC = -1, SC_OVERFLOW = -2, SC_BAD_FORMAT = -3 };
enum { SC_LED_HELM = 1, SC_LED_ROMPI = 2, SC_LED_SEPATU = 4, SC_LED_ALARM = 8 };
enum { SC_LCD_NORMAL = 0, SC_LCD_EVENT = 1, SC_LCD_URGENT = 2 };

typedef struct {
  char buf[SC_BODY_MAX + 4];   /* body + '*' + 2 hex + optional '\r' */
  uint8_t len;
  bool active, overflow, console;
  uint32_t last_ms;
} sc_framer;

typedef struct {
  int16_t pmin, phome, pmax;          /* pan */
  int16_t tmin0, tmin1, thome, tmax;  /* tilt floor at pmin / at pmax, home, top */
  int16_t pvmax, tvmax;               /* deg/s */
  int16_t pacc, tacc;                 /* deg/s^2 */
  int16_t tmaxr;                      /* tilt ceiling at pmin, rising to tmax at phome */
} sc_limits;

typedef struct {
  float pos, vel, acc, target;        /* raw trapezoid pose: dd, dd/s, (unused), dd */
  float f1, out;                      /* smoothing stage 1 and the servo output (dd) */
} sc_axis;

typedef struct {
  void (*emit)(void *user, const char *body);   /* adapter adds '$', CRC, '\n' */
  bool (*save)(void *user, const sc_limits *lim);
  bool (*load)(void *user, sc_limits *lim);
  void *user;
} sc_hooks;

typedef struct {                      /* hardware snapshot for telemetry */
  int16_t temp_a, temp_p;             /* deci-C or SC_TEMP_NA */
  uint8_t fan_a, fan_p;
  uint16_t vcc_mv;
  bool relay, sounding, lcd_ok;
} sc_hw;

typedef struct {
  sc_hooks hooks;
  sc_limits lim;
  bool calibrated, cal_mode;
  bool session, link_ok, have_seq, lost, lost_homing;
  uint32_t token, boot_ms;
  uint16_t last_seq;
  uint32_t last_s_ms, lost_ms;
  /* last accepted S frame */
  char mode;
  char items[5];                      /* helmet, vest, shoes, glove */
  bool alarm, clamped, vox;          /* vox: brain allows sound (siren + chimes) */
  uint8_t volume;                     /* 0..100 % loudness (duty-cycle shaped tone) */
  uint8_t ppl, viol;
  uint16_t trk;
  int16_t sp_pan, sp_tilt;
  /* motion */
  sc_axis pan, tilt;
  float vlimit;                       /* deg/s requested */
  bool moving;
  /* gesture animation (fx) */
  char fx;                            /* active animation N/H/C/W, 0 = none */
  char fx_started;                    /* one-shot for the sound adapter */
  bool fx_armed;
  uint8_t fx_last_id;
  float fx_ms;
  int16_t fx_base_p, fx_base_t;
  char fx_text;                       /* last animation, for the LCD event text */
  uint32_t fx_text_ms;
  /* LCD pacing */
  char lcd_rows[2][17];
  uint8_t lcd_level;
  bool lcd_init;
  uint32_t lcd_changed_ms;
  /* environment / fans: index 0 = A (Arduino), 1 = P (Pico) */
  int16_t soc_dc;
  uint32_t soc_ms;
  bool soc_valid;
  int16_t fan_manual[2];
  uint32_t fan_manual_ms[2];
  bool fan_on[2];
  /* ERR rate limit */
  uint32_t err_window_ms;
  uint8_t err_count;
} sc_ctx;

uint8_t sc_crc8(const char *data, uint8_t len);
void sc_framer_init(sc_framer *f);
/* SC_FRAME / SC_CONSOLE: NUL-terminated body copied to body_out
 * (>= SC_BODY_MAX + 1 bytes). Console lines start with '#' and carry no CRC. */
int sc_framer_feed(sc_framer *f, char c, uint32_t now_ms, char *body_out);

void sc_limits_default(sc_limits *l);
bool sc_limits_valid(const sc_limits *l);
int16_t sc_tilt_floor_i(const sc_limits *l, int16_t pan);  /* integer ceil (spec 5) */
float sc_tilt_floor_f(const sc_limits *l, float pan);      /* exact linear, <= _i */
int16_t sc_tilt_ceil_i(const sc_limits *l, int16_t pan);   /* integer floor (spec 5) */
float sc_tilt_ceil_f(const sc_limits *l, float pan);       /* exact, >= _i */
bool sc_in_zone(const sc_limits *l, float pan, float tilt);
void sc_clamp(const sc_limits *l, int16_t *pan, int16_t *tilt, bool *clamped);
uint16_t sc_dd_to_us(float dd);

void sc_init(sc_ctx *c, const sc_hooks *hooks, uint32_t now_ms);
void sc_handle(sc_ctx *c, char *body, uint32_t now_ms);    /* body is modified */
void sc_frame_error(sc_ctx *c, int code, uint32_t now_ms);
void sc_tick(sc_ctx *c, uint32_t now_ms);
void sc_motion_step(sc_ctx *c, float dt_s);
/* Boot: the servo is physically where it was at power-off. Start there and glide home. */
void sc_set_boot_pose(sc_ctx *c, int16_t pan, int16_t tilt);
/* Start an animation now: 'N' nod (yes), 'H' head shake (no), 'C' curious, 'W' greet. */
bool sc_fx_start(sc_ctx *c, char fx, uint32_t now_ms);
uint16_t sc_fx_duration(char fx);
void sc_emit_ready(sc_ctx *c);
void sc_emit_lim(sc_ctx *c);
void sc_emit_telemetry(sc_ctx *c, uint32_t now_ms, const sc_hw *hw);
uint8_t sc_fan_duty(sc_ctx *c, uint8_t idx, int16_t temp_dc, uint32_t now_ms);
/* Candidate 16-char rows (NUL at [16]), LED bitmask and urgency level. */
void sc_display(const sc_ctx *c, uint32_t now_ms, char row0[17], char row1[17],
                uint8_t *leds, uint8_t *level);
/* Pace the LCD: commits the candidate only when allowed (urgent/event at once,
 * normal text at most every SC_LCD_HOLD_MS). Returns true when the shown text changed;
 * the shown text is always in c->lcd_rows. */
bool sc_lcd_update(sc_ctx *c, uint32_t now_ms, const char row0[17], const char row1[17], uint8_t level);

#ifdef __cplusplus
}
#endif
#endif
