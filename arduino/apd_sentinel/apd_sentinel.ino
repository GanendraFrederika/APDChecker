/*
 * APD SENTINEL v3.1 - Arduino Uno R3 "muscle" for the person-lock PPE camera.
 *
 * The brain (PC now, Luckfox later) sends SLP/1 frames over USB serial at 115200.
 * All protocol, safe-zone and motion logic lives in sentinel_core.c (unit tested
 * on the PC with the very same file). This sketch only drives the hardware.
 *
 * Pin map (owner's wiring, 24-10-2026):
 *   D0/D1 USB serial (disconnect Luckfox UART wires while USB is used!)
 *   D2  DS18B20 Arduino heatsink     D3  DS18B20 Pico heatsink
 *   D4  LED helm (merah)             D5  MOSFET fan camera+Pico (PWM)
 *   D6  MOSFET fan Arduino (PWM)     D7  servo tilt (naik-turun)
 *   D8  LED alarm                    D9  audio tone -> TPA3110 input
 *   D10 relay -> TPA3110 power       D11 servo pan (kanan-kiri)
 *   D12 LED rompi (hijau)            A0  LED sepatu (kuning)
 *   A4/A5 LCD 16x2 PCF8574 SDA/SCL (confirmed on this rig, address 0x27)
 *
 * Human console (Serial Monitor 115200, newline): #HELP, #CAL,1, #JOG,P,900, #FX,N ...
 */
#include <Arduino.h>
#include <EEPROM.h>
#include <Servo.h>
#include <avr/wdt.h>
#include "sentinel_core.h"
#include "sentinel_board.h"

// ---------------------------------------------------------------- pins
const uint8_t PIN_TEMP_A = 2, PIN_TEMP_P = 3;
const uint8_t PIN_LED_HELM = 4, PIN_LED_ROMPI = 12, PIN_LED_SEPATU = A0, PIN_LED_ALARM = 8;
const uint8_t PIN_FAN_P = 5, PIN_FAN_A = 6;
const uint8_t PIN_SERVO_TILT = 7, PIN_SERVO_PAN = 11;
const uint8_t PIN_AUDIO = 9, PIN_RELAY = 10;
// Same polarity as the proven legacy sketch: HIGH = relay ON = amplifier powered.
const uint8_t RELAY_ON = HIGH, RELAY_OFF = LOW;

// ---------------------------------------------------------------- state
static sc_ctx core;
static sc_framer framer;
static char rxBody[SC_BODY_MAX + 1];
static Servo servoPan, servoTilt;
static uint16_t lastPanUs, lastTiltUs;
static sc_hw hw;
static uint8_t bootCause __attribute__((section(".noinit")));

// Read the reset cause before anything else and stop a stale watchdog (Optiboot safe).
void earlyInit(void) __attribute__((naked, used, section(".init3")));
void earlyInit(void) {
  bootCause = MCUSR;
  MCUSR = 0;
  wdt_disable();
  // Servo signals D7 (PD7) and D11 (PB3) held LOW from the first microsecond:
  // a floating signal line makes an MG996R twitch while the bootloader runs.
  PORTD &= ~_BV(7); DDRD |= _BV(7);
  PORTB &= ~_BV(3); DDRB |= _BV(3);
}

// ---------------------------------------------------------------- framing out
static void emitBody(void *, const char *body) {
  uint8_t len = strlen(body);
  uint8_t crc = sc_crc8(body, len);
  static const char hex[] = "0123456789ABCDEF";
  Serial.write('$');
  Serial.write((const uint8_t *)body, len);
  Serial.write('*');
  Serial.write(hex[crc >> 4]);
  Serial.write(hex[crc & 15]);
  Serial.write('\n');
}

static void emitf(const __FlashStringHelper *fmt, ...) {
  char b[48];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf_P(b, sizeof(b), (const char *)fmt, ap);
  va_end(ap);
  emitBody(nullptr, b);
}

// ---------------------------------------------------------------- EEPROM
const int EE_ADDR = 0;
const uint8_t EE_MAGIC0 = 'S', EE_MAGIC1 = 'N', EE_VER = 3;

static bool eeSave(void *, const sc_limits *lim) {
  const uint8_t *p = (const uint8_t *)lim;
  EEPROM.update(EE_ADDR, EE_MAGIC0);
  EEPROM.update(EE_ADDR + 1, EE_MAGIC1);
  EEPROM.update(EE_ADDR + 2, EE_VER);
  for (uint8_t i = 0; i < sizeof(sc_limits); ++i) EEPROM.update(EE_ADDR + 3 + i, p[i]);
  EEPROM.update(EE_ADDR + 3 + sizeof(sc_limits), sc_crc8((const char *)p, sizeof(sc_limits)));
  sc_limits check;
  EEPROM.get(EE_ADDR + 3, check);   // read back: SAVE is only OK if it really stuck
  return memcmp(&check, lim, sizeof(sc_limits)) == 0;
}

static bool eeLoad(void *, sc_limits *lim) {
  if (EEPROM.read(EE_ADDR) != EE_MAGIC0 || EEPROM.read(EE_ADDR + 1) != EE_MAGIC1 ||
      EEPROM.read(EE_ADDR + 2) != EE_VER) return false;
  sc_limits tmp;
  EEPROM.get(EE_ADDR + 3, tmp);
  if (EEPROM.read(EE_ADDR + 3 + sizeof(sc_limits)) != sc_crc8((const char *)&tmp, sizeof(sc_limits)))
    return false;
  *lim = tmp;
  return true;
}

// ---------------------------------------------------------------- pose memory
// Hobby servos give no position feedback. Remembering the last commanded pose lets
// the next boot start exactly there (no power-on lurch) and glide home slowly.
// Ring of 32 slots with a running counter = wear levelling (~2+ years of tracking).
const int POSE_BASE = 64;
const uint8_t POSE_SLOTS = 32, POSE_SIZE = 7;           // seq16, pan16, tilt16, crc8
static uint8_t poseNext;
static uint16_t poseSeq;
static int16_t posePan = -1, poseTilt = -1;
static uint32_t poseSavedAt, stillSince;

static bool poseRead(uint8_t slot, uint16_t &seq, int16_t &pan, int16_t &tilt) {
  uint8_t b[POSE_SIZE];
  for (uint8_t i = 0; i < POSE_SIZE; ++i) b[i] = EEPROM.read(POSE_BASE + slot * POSE_SIZE + i);
  if (sc_crc8((const char *)b, 6) != b[6]) return false;
  seq = b[0] | (b[1] << 8);
  pan = (int16_t)(b[2] | (b[3] << 8));
  tilt = (int16_t)(b[4] | (b[5] << 8));
  return pan >= 0 && pan <= 1800 && tilt >= 0 && tilt <= 1800;
}

// Newest = valid slot whose successor is not seq+1 (works across counter wrap).
static bool poseLoad(int16_t &pan, int16_t &tilt) {
  for (uint8_t i = 0; i < POSE_SLOTS; ++i) {
    uint16_t s, s2; int16_t p, t, p2, t2;
    if (!poseRead(i, s, p, t)) continue;
    uint8_t j = (i + 1) % POSE_SLOTS;
    if (poseRead(j, s2, p2, t2) && s2 == (uint16_t)(s + 1)) continue;
    pan = p; tilt = t;
    poseNext = j; poseSeq = s + 1;
    posePan = p; poseTilt = t;
    return true;
  }
  return false;
}

static void poseSave(int16_t pan, int16_t tilt) {
  uint8_t b[POSE_SIZE] = {(uint8_t)poseSeq, (uint8_t)(poseSeq >> 8), (uint8_t)pan,
                          (uint8_t)((uint16_t)pan >> 8), (uint8_t)tilt, (uint8_t)((uint16_t)tilt >> 8), 0};
  b[6] = sc_crc8((const char *)b, 6);
  for (uint8_t i = 0; i < POSE_SIZE; ++i) EEPROM.update(POSE_BASE + poseNext * POSE_SIZE + i, b[i]);
  poseNext = (poseNext + 1) % POSE_SLOTS;
  ++poseSeq;
  posePan = pan; poseTilt = tilt;
}

// Save only when the camera rests: >= 2 s still, moved >= 1 degree, max every 20 s.
static void poseService(uint32_t now) {
  if (core.moving) { stillSince = now; return; }
  if ((uint32_t)(now - stillSince) < 2000UL || (uint32_t)(now - poseSavedAt) < 20000UL) return;
  int16_t p = (int16_t)(core.pan.out + 0.5f), t = (int16_t)(core.tilt.out + 0.5f);
  if (abs(p - posePan) < 10 && abs(t - poseTilt) < 10) return;
  poseSave(p, t);
  poseSavedAt = now;
}

// ---------------------------------------------------------------- LCD (bit-bang I2C)
// Both candidate buses live on PORTC (A1/A2 and A4/A5), so plain register masks
// work. Open-drain: drive low = output 0, release = input + pull-up. Never output 1.
static uint8_t i2cSda, i2cScl, lcdAddr;
static bool lcdOk;
static char lcdShown[2][16], lcdWant[2][16];
static int8_t lcdCurRow = -1, lcdCurCol = -1;
static uint8_t lcdScan;

static inline void i2cDelay() { delayMicroseconds(5); }
static inline void sdaLow() { PORTC &= ~i2cSda; DDRC |= i2cSda; }
static inline void sdaRel() { DDRC &= ~i2cSda; PORTC |= i2cSda; }
static inline void sclLow() { PORTC &= ~i2cScl; DDRC |= i2cScl; }
static inline void sclRel() {
  DDRC &= ~i2cScl; PORTC |= i2cScl;
  for (uint8_t n = 0; n < 50 && !(PINC & i2cScl); ++n) delayMicroseconds(2);  // clock stretch
}
static void i2cStart() { sdaRel(); sclRel(); i2cDelay(); sdaLow(); i2cDelay(); sclLow(); }
static void i2cStop() { sdaLow(); i2cDelay(); sclRel(); i2cDelay(); sdaRel(); i2cDelay(); }
static bool i2cWrite(uint8_t b) {
  for (uint8_t i = 0; i < 8; ++i, b <<= 1) {
    if (b & 0x80) sdaRel(); else sdaLow();
    i2cDelay(); sclRel(); i2cDelay(); sclLow();
  }
  sdaRel(); i2cDelay(); sclRel(); i2cDelay();
  bool ack = !(PINC & i2cSda);
  sclLow();
  return ack;
}

const uint8_t LCD_RS = 0x01, LCD_EN = 0x04, LCD_BL = 0x08;  // standard PCF8574 backpack map

static void lcdSend(uint8_t value, uint8_t rs) {
  uint8_t hi = (value & 0xF0) | rs | LCD_BL, lo = ((value << 4) & 0xF0) | rs | LCD_BL;
  i2cStart();
  i2cWrite(lcdAddr << 1);
  i2cWrite(hi | LCD_EN); i2cWrite(hi);   // each byte is >= 90 us: EN pulse is long enough
  i2cWrite(lo | LCD_EN); i2cWrite(lo);
  i2cStop();
}

static void lcdNibble(uint8_t nib) {
  uint8_t v = (nib << 4) | LCD_BL;
  i2cStart(); i2cWrite(lcdAddr << 1); i2cWrite(v | LCD_EN); i2cWrite(v); i2cStop();
}

static bool busIdleHigh() {
  sdaRel(); sclRel(); delayMicroseconds(50);
  return (PINC & i2cSda) && (PINC & i2cScl);
}

static bool lcdProbe(uint8_t sdaMask, uint8_t sclMask, const char *&busName, const char *name) {
  i2cSda = sdaMask; i2cScl = sclMask;
  if (!busIdleHigh()) { DDRC &= ~(sdaMask | sclMask); PORTC &= ~(sdaMask | sclMask); return false; }
  static const uint8_t addrs[] = {0x27, 0x3F};   // PCF8574 / PCF8574A defaults
  for (uint8_t i = 0; i < sizeof(addrs); ++i) {
    i2cStart();
    bool ack = i2cWrite(addrs[i] << 1);
    i2cStop();
    if (ack) { lcdAddr = addrs[i]; busName = name; return true; }
  }
  DDRC &= ~(sdaMask | sclMask); PORTC &= ~(sdaMask | sclMask);
  return false;
}

static void lcdInit() {
  const char *bus = "NONE";
  // Boot log 24-10-2026 confirmed this rig: backpack 0x27 on A4/A5 (hardware I2C pins).
  lcdOk = lcdProbe(_BV(4), _BV(5), bus, "A4A5");
  if (lcdOk) {
    delay(50);
    lcdNibble(0x03); delay(5); lcdNibble(0x03); delayMicroseconds(150); lcdNibble(0x03);
    lcdNibble(0x02);                       // 4-bit mode
    lcdSend(0x28, 0);                      // 2 lines, 5x8 font
    lcdSend(0x0C, 0);                      // display on, cursor off
    lcdSend(0x01, 0); delay(2);            // clear
    lcdSend(0x06, 0);                      // entry mode: increment
    memset(lcdShown, ' ', sizeof(lcdShown));
    lcdCurRow = lcdCurCol = -1;
  }
  emitf(F("EVT,LCD,%02X,%s"), lcdOk ? lcdAddr : 0, bus);
}

// Incremental refresh: at most 2 characters per loop so UART never starves.
static void lcdService() {
  if (!lcdOk) return;
  for (uint8_t budget = 2; budget; ) {
    uint8_t i = 0;
    for (; i < 32; ++i) {
      uint8_t k = (lcdScan + i) & 31, r = k >> 4, col = k & 15;
      if (lcdShown[r][col] != lcdWant[r][col]) {
        if (lcdCurRow != r || lcdCurCol != col) lcdSend(0x80 | (r ? 0x40 : 0) | col, 0);
        lcdSend(lcdWant[r][col], LCD_RS);
        lcdShown[r][col] = lcdWant[r][col];
        lcdCurRow = r;
        lcdCurCol = col + 1;
        lcdScan = k + 1;
        --budget;
        break;
      }
    }
    if (i == 32) return;
  }
}

// ---------------------------------------------------------------- DS18B20 (1-Wire)
// Only the few microseconds that decide a bit run with interrupts off, so the
// Servo timer ISR is delayed at most ~13 us (well below visible servo jitter).
static OneWirePin owA, owP;

static void owSetup(OneWirePin &o, uint8_t pin) {
  uint8_t port = digitalPinToPort(pin);
  o.mode = portModeRegister(port);
  o.out = portOutputRegister(port);
  o.in = portInputRegister(port);
  o.mask = digitalPinToBitMask(pin);
  o.lastDc = SC_TEMP_NA;
  o.present = false;
  *o.mode &= ~o.mask; *o.out |= o.mask;      // released + internal pull-up
}
static inline void owLow(OneWirePin &o) { *o.out &= ~o.mask; *o.mode |= o.mask; }
static inline void owRel(OneWirePin &o) { *o.mode &= ~o.mask; *o.out |= o.mask; }

static bool owReset(OneWirePin &o) {
  owRel(o);
  for (uint8_t n = 0; !(*o.in & o.mask); ++n) { if (n > 125) return false; delayMicroseconds(2); }
  noInterrupts(); owLow(o); interrupts();
  delayMicroseconds(480);
  noInterrupts(); owRel(o); interrupts();
  delayMicroseconds(70);
  bool presence = !(*o.in & o.mask);
  delayMicroseconds(410);
  return presence;
}

static void owWriteBit(OneWirePin &o, bool bit) {
  if (bit) {
    noInterrupts(); owLow(o); delayMicroseconds(6); owRel(o); interrupts();
    delayMicroseconds(64);
  } else {
    noInterrupts(); owLow(o); interrupts();
    delayMicroseconds(60);
    noInterrupts(); owRel(o); interrupts();
    delayMicroseconds(10);
  }
}

static bool owReadBit(OneWirePin &o) {
  noInterrupts();
  owLow(o); delayMicroseconds(3); owRel(o); delayMicroseconds(10);
  bool bit = *o.in & o.mask;
  interrupts();
  delayMicroseconds(53);
  return bit;
}

static void owWrite(OneWirePin &o, uint8_t v) { for (uint8_t i = 0; i < 8; ++i, v >>= 1) owWriteBit(o, v & 1); }
static uint8_t owRead(OneWirePin &o) {
  uint8_t v = 0;
  for (uint8_t i = 0; i < 8; ++i) if (owReadBit(o)) v |= 1 << i;
  return v;
}

static uint8_t dallasCrc(const uint8_t *p, uint8_t n) {
  uint8_t crc = 0;
  while (n--) {
    uint8_t in = *p++;
    for (uint8_t i = 0; i < 8; ++i, in >>= 1) {
      uint8_t mix = (crc ^ in) & 1;
      crc >>= 1;
      if (mix) crc ^= 0x8C;
    }
  }
  return crc;
}

static void tempStart(OneWirePin &o) {
  if (owReset(o)) { owWrite(o, 0xCC); owWrite(o, 0x44); }   // skip ROM, convert
}

static void tempRead(OneWirePin &o, char which) {
  int16_t dc = SC_TEMP_NA;
  if (owReset(o)) {
    uint8_t s[9];
    owWrite(o, 0xCC); owWrite(o, 0xBE);                        // read scratchpad
    for (uint8_t i = 0; i < 9; ++i) s[i] = owRead(o);
    bool allSame = true;
    for (uint8_t i = 1; i < 9; ++i) allSame &= s[i] == s[0];
    if (!allSame && dallasCrc(s, 8) == s[8]) {
      int16_t raw = (int16_t)((s[1] << 8) | s[0]);            // 1/16 C
      int32_t v = ((int32_t)raw * 10 + (raw >= 0 ? 8 : -8)) / 16;
      if (v >= -550 && v <= 1250) dc = (int16_t)v;
    }
  }
  bool present = dc != SC_TEMP_NA;
  if (present != o.present) emitf(F("EVT,TEMP,%c,%s"), which, present ? "OK" : "ABSENT");
  o.present = present;
  o.lastDc = dc;
}

// ---------------------------------------------------------------- Vcc monitor
static uint16_t readVccMv() {
  ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);   // AVcc ref, read 1.1 V bandgap
  delayMicroseconds(400);
  ADCSRA |= _BV(ADSC); while (bit_is_set(ADCSRA, ADSC)) {}  // discard first sample
  ADCSRA |= _BV(ADSC); while (bit_is_set(ADCSRA, ADSC)) {}
  uint16_t adc = ADC;
  return adc ? (uint16_t)(1125300UL / adc) : 0;
}

// ---------------------------------------------------------------- audio
// Timer2 drives D9? No: D9 is OC1A (Timer1) which Servo owns, so tone() runs on
// Timer2 and toggles D9 in software. Loudness comes from the duty cycle instead:
// a 50 % square wave is full volume, shorter pulses carry less energy. We emulate
// the duty by gating the tone in short bursts (10 ms frames) - simple and
// timer-free. The relay powers the amplifier only while sound is wanted, so servo
// noise never reaches the speaker the rest of the time.
static const ToneStep SIREN[] = {{1050, 230}, {760, 230}, {1050, 230}, {760, 230},
                                 {1050, 230}, {760, 230}, {0, 520}};
const uint8_t SIREN_STEPS = sizeof(SIREN) / sizeof(SIREN[0]);
// Friendly chimes, short and soft (played once per animation event).
static const ToneStep CHIME_YES[] = {{880, 90}, {0, 40}, {1320, 160}};                    // nod
static const ToneStep CHIME_NO[] = {{520, 160}, {0, 60}, {390, 220}};                     // shake
static const ToneStep CHIME_HI[] = {{988, 90}, {1319, 90}, {1568, 90}, {0, 30}, {2093, 170}};  // greet
static const ToneStep CHIME_HMM[] = {{700, 80}, {0, 60}, {820, 80}};                      // curious

static bool audioWanted, audioActive;
static uint8_t audioStep, audioLen;
static const ToneStep *audioSeq;
static bool audioLoop;
static uint32_t audioStepAt, relayOnAt, relayOffAt, gateAt;
static uint16_t audioHz;
static bool gateOn;

static void startSeq(const ToneStep *seq, uint8_t len, bool loop) {
  audioSeq = seq; audioLen = len; audioLoop = loop;
  audioStep = 0xFF;
  audioStepAt = 0;
}

static void playTone(uint16_t hz) {
  audioHz = hz;
  if (hz) tone(PIN_AUDIO, hz); else noTone(PIN_AUDIO);
  gateOn = hz != 0;
}

// Volume gate: in each 10 ms frame the tone is on for volume% of the time.
static void gateService(uint32_t now) {
  if (!audioHz || core.volume >= 100) return;
  uint32_t phase = (now - gateAt) % 10;
  bool want = phase < (uint32_t)core.volume / 10;
  if (want != gateOn) {
    if (want) tone(PIN_AUDIO, audioHz); else noTone(PIN_AUDIO);
    gateOn = want;
  }
}

static void audioService(uint32_t now) {
  bool alarm = core.alarm && core.link_ok && !core.cal_mode && core.vox;
  // A new animation chooses a one-shot chime; the siren has priority.
  if (core.fx_started) {
    char fx = core.fx_started;
    core.fx_started = 0;
    if (!alarm && core.vox && core.link_ok) {
      if (fx == 'N') startSeq(CHIME_YES, 3, false);
      else if (fx == 'H') startSeq(CHIME_NO, 3, false);
      else if (fx == 'W') startSeq(CHIME_HI, 5, false);
      else startSeq(CHIME_HMM, 3, false);
    }
  }
  if (alarm && (audioSeq != SIREN)) startSeq(SIREN, SIREN_STEPS, true);
  if (!alarm && audioSeq == SIREN) audioSeq = nullptr;
  bool want = audioSeq != nullptr;
  if (want && !audioWanted) {
    digitalWrite(PIN_RELAY, RELAY_ON);
    hw.relay = true;
    relayOnAt = now;
    audioActive = false;
  }
  if (!want && audioWanted) {
    playTone(0);
    digitalWrite(PIN_LED_ALARM, LOW);
    audioActive = false;
    relayOffAt = now;
  }
  audioWanted = want;
  if (!want) {
    if (hw.relay && (uint32_t)(now - relayOffAt) >= 150UL) {   // let the tone decay first
      digitalWrite(PIN_RELAY, RELAY_OFF);
      hw.relay = false;
    }
    hw.sounding = false;
    return;
  }
  if (!audioActive) {
    if ((uint32_t)(now - relayOnAt) < 150UL) return;          // amplifier power-up time
    audioActive = true;
    gateAt = now;
  }
  if (audioStep == 0xFF || (uint32_t)(now - audioStepAt) >= audioSeq[audioStep].ms) {
    uint8_t next = audioStep == 0xFF ? 0 : audioStep + 1;
    if (next >= audioLen) {
      if (!audioLoop) { audioSeq = nullptr; playTone(0); return; }
      next = 0;
    }
    audioStep = next;
    audioStepAt = now;
    playTone(audioSeq[audioStep].hz);
    if (audioSeq == SIREN) digitalWrite(PIN_LED_ALARM, SIREN[audioStep].hz > 900 ? HIGH : LOW);
  }
  gateService(now);
  hw.sounding = audioSeq == SIREN;
}

// ---------------------------------------------------------------- console
static void console(char *line) {
  for (char *p = line; *p; ++p) if (*p >= 'a' && *p <= 'z') *p -= 32;   // case-insensitive
  if (!strcmp(line, "HELP")) {
    // Full command list: docs/sentinel/PROTOCOL.md (kept out of flash to fit the Uno).
    Serial.println(F("# CAL,1 JOG,P,900 SET,T,MIN0,1450 SAVE CAL,0 VOL,50 FX,N|H|C|W"));
    return;
  }
  if (!strncmp(line, "FX,", 3) && line[3] && !line[4]) {
    if (!sc_fx_start(&core, line[3], millis())) Serial.println(F("# FX: N/H/C/W, bukan saat CAL"));
    return;
  }
  // Everything else is a protocol body; session-bound commands stay brain-only.
  if (!strncmp(line, "S,", 2) || !strncmp(line, "HELLO", 5) || !strncmp(line, "ENV", 3)) {
    Serial.println(F("# perintah ini hanya untuk AI"));
    return;
  }
  sc_handle(&core, line, millis());
}

// ---------------------------------------------------------------- setup / loop
static uint32_t lastMotionUs, lastTelemetry, lastDisplay, lastFan, lastVcc, vccWindowAt;
static uint32_t tempAt, lastVccEvt;
static uint8_t tempPhase;
static uint16_t vccMin = 0xFFFF;

static void writeServos() {
  uint16_t p = sc_dd_to_us(core.pan.out), t = sc_dd_to_us(core.tilt.out);
  if (p != lastPanUs) { servoPan.writeMicroseconds(p); lastPanUs = p; }
  if (t != lastTiltUs) { servoTilt.writeMicroseconds(t); lastTiltUs = t; }
}

void setup() {
  pinMode(PIN_RELAY, OUTPUT); digitalWrite(PIN_RELAY, RELAY_OFF);   // amp OFF first
  pinMode(PIN_AUDIO, OUTPUT); digitalWrite(PIN_AUDIO, LOW);
  pinMode(PIN_LED_HELM, OUTPUT); pinMode(PIN_LED_ROMPI, OUTPUT);
  pinMode(PIN_LED_SEPATU, OUTPUT); pinMode(PIN_LED_ALARM, OUTPUT);
  pinMode(PIN_FAN_A, OUTPUT); pinMode(PIN_FAN_P, OUTPUT);
  analogWrite(PIN_FAN_A, 160); analogWrite(PIN_FAN_P, 160);         // cool until sensors read
  Serial.begin(115200);
  sc_hooks hooks = {emitBody, eeSave, eeLoad, nullptr};
  sc_framer_init(&framer);
  sc_init(&core, &hooks, millis());
  int16_t bootPan, bootTilt;
  bool havePose = poseLoad(bootPan, bootTilt);
  if (havePose) sc_set_boot_pose(&core, bootPan, bootTilt);
  // The first pulse equals the remembered pose, so attach() causes no lurch;
  // the motion profile then glides home at the slow calibration speed.
  writeServos();
  servoPan.attach(PIN_SERVO_PAN, 544, 2400);
  servoTilt.attach(PIN_SERVO_TILT, 544, 2400);
  emitf(F("EVT,BOOT,%02X"), bootCause & 0x0F);
  if (havePose) emitf(F("EVT,POSE,%d,%d"), bootPan, bootTilt);
  else emitf(F("EVT,POSE,NONE"));
  lcdInit();
  owSetup(owA, PIN_TEMP_A);
  owSetup(owP, PIN_TEMP_P);
  hw.temp_a = hw.temp_p = SC_TEMP_NA;
  hw.fan_a = hw.fan_p = 160;
  lastMotionUs = micros();
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  uint32_t now = millis();

  // 1. UART: bounded work per pass so motion and display keep their cadence.
  for (uint8_t n = 0; n < 96 && Serial.available() > 0; ++n) {
    int r = sc_framer_feed(&framer, (char)Serial.read(), millis(), rxBody);
    if (r == SC_FRAME) sc_handle(&core, rxBody, millis());
    else if (r == SC_CONSOLE) console(rxBody);
    else if (r < 0) sc_frame_error(&core, r, millis());
  }
  sc_tick(&core, now);

  // 2. Motion at 50 Hz (servo frame rate), dt from micros() for smooth profiles.
  uint32_t us = micros();
  if ((uint32_t)(us - lastMotionUs) >= 20000UL) {
    sc_motion_step(&core, (us - lastMotionUs) * 1e-6f);
    lastMotionUs = us;
    writeServos();
    poseService(millis());
  }

  // 3. Siren, chimes and amplifier relay.
  audioService(now);

  // 4. Display + item LEDs (10 Hz) and incremental LCD refresh.
  if ((uint32_t)(now - lastDisplay) >= 100UL) {
    lastDisplay = now;
    char r0[17], r1[17];
    uint8_t leds, level;
    sc_display(&core, now, r0, r1, &leds, &level);
    if (sc_lcd_update(&core, now, r0, r1, level)) {   // normal text: max 1 change / 3 s
      memcpy(lcdWant[0], core.lcd_rows[0], 16);
      memcpy(lcdWant[1], core.lcd_rows[1], 16);
    }
    digitalWrite(PIN_LED_HELM, (leds & SC_LED_HELM) ? HIGH : LOW);
    digitalWrite(PIN_LED_ROMPI, (leds & SC_LED_ROMPI) ? HIGH : LOW);
    digitalWrite(PIN_LED_SEPATU, (leds & SC_LED_SEPATU) ? HIGH : LOW);
    if (!hw.sounding) digitalWrite(PIN_LED_ALARM, (leds & SC_LED_ALARM) ? HIGH : LOW);
  }
  lcdService();

  // 5. Temperatures: convert both, read one per pass, and never while RX is busy.
  if (tempPhase == 0 && (uint32_t)(now - tempAt) >= 2000UL) {
    tempStart(owA); tempStart(owP); tempAt = now; tempPhase = 1;
  } else if (tempPhase == 1 && (uint32_t)(now - tempAt) >= 800UL && Serial.available() < 16) {
    tempRead(owA, 'A'); hw.temp_a = owA.lastDc; tempPhase = 2;
  } else if (tempPhase == 2 && Serial.available() < 16) {
    tempRead(owP, 'P'); hw.temp_p = owP.lastDc; tempPhase = 0;
  }

  // 6. Fans (1 Hz).
  if ((uint32_t)(now - lastFan) >= 1000UL) {
    lastFan = now;
    hw.fan_a = sc_fan_duty(&core, 0, hw.temp_a, now);
    hw.fan_p = sc_fan_duty(&core, 1, hw.temp_p, now);
    analogWrite(PIN_FAN_A, hw.fan_a);
    analogWrite(PIN_FAN_P, hw.fan_p);
  }

  // 7. Supply monitor: servos stalling on a weak 5 V rail show up here first.
  if ((uint32_t)(now - lastVcc) >= 250UL) {
    lastVcc = now;
    uint16_t v = readVccMv();
    if (v && v < vccMin) vccMin = v;
    if (v && v < 4500 && (uint32_t)(now - lastVccEvt) >= 1000UL) {
      lastVccEvt = now;
      emitf(F("EVT,VCC,%u"), v);
    }
    if ((uint32_t)(now - vccWindowAt) >= 1000UL) {
      vccWindowAt = now;
      hw.vcc_mv = vccMin == 0xFFFF ? 0 : vccMin;
      vccMin = 0xFFFF;
    }
  }

  // 8. Telemetry at 20 Hz.
  if ((uint32_t)(now - lastTelemetry) >= 50UL) {
    lastTelemetry = now;
    hw.lcd_ok = lcdOk;
    sc_emit_telemetry(&core, now, &hw);
  }
}
