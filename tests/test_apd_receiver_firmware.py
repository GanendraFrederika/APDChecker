"""Compile the real legacy sketch with host mocks; never open a serial port."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "arduino/legacy/apd_receiver/apd_receiver.ino"

ARDUINO = r'''
#pragma once
#include <stdint.h>
#include <string>
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT 0
#define A0 14
#define A1 15
#define F(text) text
inline unsigned long nowMs = 0;
inline int levels[20] = {};
inline int modes[20] = {};
inline int frequency = 0;
inline int delayCalls = 0;
inline int adcValue = 543, adcCalls = 0, adcPin = -1;
inline int analogRead(int pin) { ++adcCalls; adcPin = pin; return adcValue; }
inline unsigned long fakeIoCost = 0;
inline unsigned long millis() { return nowMs; }
inline void delay(unsigned long) { ++delayCalls; }
inline void pinMode(int pin, int mode) { modes[pin] = mode; }
inline void digitalWrite(int pin, int value) { levels[pin] = value; nowMs += fakeIoCost; }
inline void tone(int, int value) { frequency = value; }
inline void noTone(int) { frequency = 0; }
struct FakeSerial {
  std::string pending;
  int baud = 0;
  std::string log;
  void begin(int value) { baud = value; }
  int available() { return pending.size(); }
  char read() { char value = pending.front(); pending.erase(0, 1); return value; }
  void print(const char *text) { log += text; }
  void print(int value) { log += std::to_string(value); }
  template<class T> void println(T value) { print(value); log += '\n'; }
};
inline FakeSerial Serial;
'''
WIRE = r'''
#pragma once
#include <Arduino.h>
#define WIRE_HAS_TIMEOUT 1
struct FakeWire {
  int result = 0, address = 0;
  unsigned long timeout = 0;
  void begin() {}
  void setWireTimeout(unsigned long value, bool) { timeout = value; }
  void beginTransmission(int value) { address = value; }
  int endTransmission() { return result; }
};
inline FakeWire Wire;
'''
# Behavioral fake only: target scheduling, cubic interpolation and cancellation.
# The actual ServoEasing implementation is separately compiled by Arduino CLI.
SERVO = r'''
#pragma once
#include <Arduino.h>
#include <cmath>
#include <vector>
#define EASE_CUBIC_IN_OUT 0x82
struct ServoEasing {
  int pin = -1, angle = -1, easing = -1, updateCalls = 0;
  double position = 90, startPosition = 90;
  unsigned long started = 0, duration = 0;
  int target = 90;
  bool moving = false;
  std::vector<int> targets, completed;
  void attach(int value, int initial) { pin = value; angle = initial; position = initial; }
  void setEasingType(int value) { easing = value; }
  bool setEaseTo(int value, uint_fast16_t speed) {
    targets.push_back(value);
    startPosition = position; target = value; started = millis();
    duration = std::abs(value - read()) * 1000UL / speed;
    const bool wasStopped = !moving;
    moving = true;
    return wasStopped;
  }
  bool isMoving() { return moving; }
  int read() { return static_cast<int>(std::lround(position)); }
  void stop() { moving = false; }
  bool update() {
    ++updateCalls;
    if (!moving) return true;
    const unsigned long elapsed = millis() - started;
    if (elapsed >= duration) {
      position = target; angle = target; moving = false; completed.push_back(target);
      return true;
    }
    const double x = double(elapsed) / duration;
    const double y = x < .5 ? 4*x*x*x : 1 - std::pow(-2*x+2, 3)/2;
    position = startPosition + (target-startPosition)*y;
    angle = read();
    return false;
  }
};
'''
LCD = r'''
#pragma once
#include <Arduino.h>
struct LiquidCrystal_PCF8574 {
  int address, cols = 0, rows = 0, backlight = 0, row = 0, writes = 0;
  std::string lines[2];
  LiquidCrystal_PCF8574(int value) : address(value) {}
  void begin(int c, int r) { cols = c; rows = r; }
  void setBacklight(int value) { backlight = value; }
  void setCursor(int, int value) { row = value; }
  void print(const char *text) { ++writes; lines[row] = text; }
};
'''
HARNESS = r'''
#include <Arduino.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "SKETCH_PATH"
#define CHECK(expr) do { if (!(expr)) { std::fprintf(stderr, "line %d: %s\n", __LINE__, #expr); return 1; } } while (0)
void tick(unsigned long time) { nowMs = time; loop(); }
void send(char command, unsigned long time) { Serial.pending.assign(1, command); tick(time); }
void bytes(const std::string &data, unsigned long time) {
  Serial.pending += data;
  do { tick(time); } while (Serial.available());
}
std::string packet(char state, int mask) {
  char body[16], wire[24];
  std::snprintf(body, sizeof(body), "PPE,%c,%d", state, mask);
  unsigned int checksum = 0;
  for (const char *p = body; *p; ++p) checksum ^= (unsigned char)*p;
  std::snprintf(wire, sizeof(wire), "!%s*%02X\n", body, checksum);
  return wire;
}
void status(char state, int mask, unsigned long time) { bytes(packet(state, mask), time); }
bool lamps(int red, int yellow, int green) {
  return levels[ind_helm_m] == red && levels[ind_sepatu_k] == yellow && levels[ind_rompi_h] == green;
}
int main(int argc, char **argv) {
  CHECK(argc == 2);
  const char *test = argv[1];
  if (!std::strcmp(test, "missing_lcd")) Wire.result = 2;
  if (!std::strcmp(test, "rollover")) nowMs = 0xfffffe00UL;
  setup();
  const unsigned long start = nowMs;
  if (!std::strcmp(test, "boot")) {
    CHECK(Serial.baud == 9600 && levels[PIN_RELAY] == RELAY_MATI);
    CHECK(lcd.cols == 16 && lcd.rows == 2 && lcd.backlight == 255);
    CHECK(lcd.address == 0x27 && Wire.address == LCD_I2C_ADDRESS);
    CHECK(lcd.lines[0] == "Hello World" && lcd.lines[1] == "Inisialisasi...");
    CHECK(Wire.timeout == 25000UL);
    CHECK(cctvServo.pin == 11 && cctvServo.angle == 90);
    CHECK(cctvServo.easing == EASE_CUBIC_IN_OUT && !cctvServo.isMoving());
    CHECK(modes[4] == OUTPUT && modes[A0] == OUTPUT && modes[12] == OUTPUT);
    CHECK(modes[2] == 0 && modes[3] == 0 && modes[5] == 0 && modes[6] == 0 && modes[7] == 0 && modes[13] == 0);
    CHECK(PIN_DS18B20_ARDUINO == 2 && PIN_DS18B20_PICO == 3 && PIN_SERVO_TILT == 7);
    CHECK(PIN_KIPAS_PICO == 5 && PIN_KIPAS_ARDUINO == 6);
    CHECK(lamps(0, 0, 0) && adcCalls == 0);
  } else if (!std::strcmp(test, "traffic")) {
    for (unsigned long t = 0; t <= 10000; t += 500) {
      tick(t); CHECK(lamps(0, 0, 0) && adcCalls == 0);
    }
    CHECK(levels[PIN_RELAY] == RELAY_MATI && frequency == 0);
  } else if (!std::strcmp(test, "alarm")) {
    send('1', 5000); CHECK(lamps(1, 0, 0));
    CHECK(levels[PIN_RELAY] == RELAY_AKTIF && frequency == 750 && levels[8] == 1);
    tick(5499); CHECK(lamps(1, 0, 0));
    tick(5500); CHECK(lamps(0, 1, 0));
    tick(5820); CHECK(frequency == 0 && levels[8] == 0);
    tick(6000); CHECK(frequency == 750 && levels[8] == 1 && lamps(0, 0, 1));
    send('0', 6010); CHECK(frequency == 0 && levels[10] == RELAY_MATI && lamps(0, 0, 0));
  } else if (!std::strcmp(test, "return_interrupt")) {
    send('T', 5000); CHECK(servoAngle == 90); // No snap to zero.
    tick(5020); tick(7020); CHECK(servoAngle > 0 && servoAngle < 90);
    send('1', 7021); const int locked = servoAngle;
    const double lockedPulse = cctvServo.position;
    tick(8021); CHECK(servoAngle == locked && cctvServo.position == lockedPulse);
    send('0', 8100); CHECK(currentState == STATE_RETURNING_NORMAL);
    CHECK(servoAngle == locked && levels[10] == RELAY_MATI);
    tick(9000); CHECK(servoAngle > locked && cctvServo.isMoving());
    const double interrupted = cctvServo.position;
    send('A', 9001); CHECK(currentState == STATE_LOCKED_ALARM && levels[10] == RELAY_AKTIF);
    tick(10000); CHECK(cctvServo.position == interrupted && !cctvServo.isMoving());
  } else if (!std::strcmp(test, "return_repeated_safe")) {
    send('T', 5000); tick(5020); tick(7020); send('S', 7021);
    const auto planned = cctvServo.targets.size();
    for (unsigned long t = 7022; t <= 11000; ++t) send('0', t);
    CHECK(servoAngle == 90 && currentState == STATE_IDLE_STANDBY);
    CHECK(cctvServo.targets.size() == planned); // Repeated SAFE never restarts easing.
    CHECK(lamps(0, 0, 0));
  } else if (!std::strcmp(test, "relay_test")) {
    send('R', 0); CHECK(relayTestActive && levels[10] == RELAY_AKTIF);
    tick(1000); CHECK(lamps(0, 0, 0));
    tick(2000); CHECK(lamps(0, 0, 0));
    tick(2999); CHECK(levels[10] == RELAY_AKTIF);
    tick(3000); CHECK(!relayTestActive && levels[10] == RELAY_MATI);
  } else if (!std::strcmp(test, "relay_alarm_priority")) {
    send('r', 5000); send('1', 5100); tick(8000);
    CHECK(!relayTestActive && currentState == STATE_LOCKED_ALARM && levels[10] == RELAY_AKTIF);
    send('R', 8010); tick(12000);
    CHECK(currentState == STATE_LOCKED_ALARM && levels[10] == RELAY_AKTIF);
    CHECK(Serial.log.find("RELAY_TEST_SKIPPED_ALARM_ACTIVE") != std::string::npos);
    send('S', 12001); CHECK(levels[10] == RELAY_MATI);
  } else if (!std::strcmp(test, "patrol")) {
    tick(59999); CHECK(currentState == STATE_IDLE_STANDBY);
    tick(60000); CHECK(currentState == STATE_PATROLLING && servoAngle == 90);
    unsigned long t = 60000;
    while (currentState == STATE_PATROLLING && t < 100000) {
      t += 20; tick(t);
      CHECK(servoAngle >= 0 && servoAngle <= 130 && levels[10] == RELAY_MATI);
    }
    const std::vector<int> expected = {90, 0, 130, 0, 130, 90};
    CHECK(cctvServo.targets == expected && cctvServo.completed == expected);
    CHECK(servoAngle == 90 && currentState == STATE_IDLE_STANDBY && lastIdleTimer == t);
    tick(t + 59999); CHECK(currentState == STATE_IDLE_STANDBY);
    tick(t + 60000); CHECK(currentState == STATE_PATROLLING && servoAngle == 90);
    CHECK(Serial.log.find("PATROL_DONE_RESET_1_MIN") != std::string::npos);
  } else if (!std::strcmp(test, "manual_patrol")) {
    send('t', 5000); CHECK(currentState == STATE_PATROLLING && servoAngle == 90);
    for (unsigned long t = 5020; t <= 30000; t += 20) tick(t);
    CHECK(currentState == STATE_IDLE_STANDBY && servoAngle == 90);
    CHECK((cctvServo.completed == std::vector<int>{90, 0, 130, 0, 130, 90}));
  } else if (!std::strcmp(test, "repeated_patrol")) {
    send('T', 5000);
    for (unsigned long t = 5001; t <= 30000; ++t) {
      if (currentState == STATE_PATROLLING) send('T', t); else tick(t);
    }
    CHECK(currentState == STATE_IDLE_STANDBY);
    CHECK((cctvServo.targets == std::vector<int>{90, 0, 130, 0, 130, 90}));
  } else if (!std::strcmp(test, "cubic_and_cadence")) {
    send('T', 5000); tick(5020); // Start 90 -> 0.
    const int updates = cctvServo.updateCalls;
    tick(5039); CHECK(cctvServo.updateCalls == updates);
    tick(5040); CHECK(cctvServo.updateCalls == updates + 1);
    const unsigned long duration = cctvServo.duration;
    tick(5020 + duration/4);
    CHECK(cctvServo.position > 80 && cctvServo.position < 90); // cubic, not linear 67.5.
    const double quarter = cctvServo.position;
    tick(5020 + duration/2);
    CHECK(cctvServo.position > 44 && cctvServo.position < 46);
    const double half = cctvServo.position;
    tick(5020 + duration*3/4);
    CHECK(cctvServo.position > 4 && cctvServo.position < 7);
    CHECK(quarter-half > 90-quarter); // Smooth acceleration after start.
    const auto targets = cctvServo.targets.size();
    tick(5020 + duration - 1); // Rounded read() may already say zero: NOT finished.
    CHECK(cctvServo.isMoving() && cctvServo.targets.size() == targets);
    tick(5020 + duration + 20);
    CHECK(cctvServo.targets.size() == targets + 1 && cctvServo.target == 130);
  } else if (!std::strcmp(test, "patrol_restart_off_center")) {
    send('T', 5000); tick(5020); tick(7020); send('1', 7021);
    const double lockedPulse = cctvServo.position;
    send('t', 7100);
    CHECK(cctvServo.position == lockedPulse && cctvServo.target == 90);
    CHECK(levels[10] == RELAY_MATI && currentState == STATE_PATROLLING);
    tick(7600); CHECK(cctvServo.position > lockedPulse && cctvServo.position < 90);
    for (unsigned long t = 7620; t <= 35000; t += 20) tick(t);
    CHECK(currentState == STATE_IDLE_STANDBY && servoAngle == 90);
    CHECK((cctvServo.targets == std::vector<int>{90, 0, 90, 0, 130, 0, 130, 90}));
  } else if (!std::strcmp(test, "alarm_cancels_remaining_patrol")) {
    send('T', 5000); tick(5020); tick(7020); send('A', 7021);
    const auto targets = cctvServo.targets.size();
    const double lockedPulse = cctvServo.position;
    for (unsigned long t = 7040; t <= 90000; t += 20) tick(t);
    CHECK(currentState == STATE_LOCKED_ALARM && levels[10] == RELAY_AKTIF);
    CHECK(cctvServo.position == lockedPulse && cctvServo.targets.size() == targets);
    send('S', 90001);
    for (unsigned long t = 90021; t <= 94001; t += 20) tick(t);
    CHECK(currentState == STATE_IDLE_STANDBY && servoAngle == 90);
    CHECK(cctvServo.targets.size() == targets + 1 && levels[10] == RELAY_MATI);
  } else if (!std::strcmp(test, "safe_cancels_patrol")) {
    send('T', 5000); tick(5020); tick(7020); send('0', 7021);
    const auto targets = cctvServo.targets.size();
    for (unsigned long t = 7041; t <= 11001; t += 20) tick(t);
    CHECK(currentState == STATE_IDLE_STANDBY && servoAngle == 90);
    CHECK(cctvServo.targets.size() == targets && levels[10] == RELAY_MATI);
  } else if (!std::strcmp(test, "patrol_rollover")) {
    nowMs = 0xffffff00UL;
    send('T', nowMs); tick(nowMs + 20UL);
    unsigned long t = nowMs;
    for (int i = 0; i < 1300; ++i) { t += 20UL; tick(t); }
    CHECK(currentState == STATE_IDLE_STANDBY && servoAngle == 90);
    CHECK((cctvServo.completed == std::vector<int>{90, 0, 130, 0, 130, 90}));
  } else if (!std::strcmp(test, "missing_lcd")) {
    CHECK(lcd.cols == 0 && Serial.log.find("WARN:LCD_NOT_FOUND") != std::string::npos);
    tick(1000); CHECK(lamps(0, 0, 0));
    send('A', 5000); CHECK(currentState == STATE_LOCKED_ALARM && levels[10] == RELAY_AKTIF);
  } else if (!std::strcmp(test, "rollover")) {
    tick(start + 499UL); CHECK(lamps(0, 0, 0));
    status('V', 1, 0xffffff00UL);
    tick(uint32_t(0xffffff00UL + 499UL)); CHECK(lamps(1, 0, 0));
    tick(uint32_t(0xffffff00UL + 500UL)); CHECK(lamps(0, 0, 0));
    tick(uint32_t(0xffffff00UL + 1000UL)); CHECK(lamps(1, 0, 0));
    tick(uint32_t(0xffffff00UL + 3000UL)); CHECK(currentState == STATE_MONITOR_FAULT);
  } else if (!std::strcmp(test, "command_clock_advance")) {
    fakeIoCost = 1; // Hardware/API work advances millis within a single loop.
    send('S', 5000);
    CHECK(currentState == STATE_IDLE_STANDBY && cctvServo.targets.empty());
    CHECK(lastIdleTimer > 5000 && levels[10] == RELAY_MATI);
    send('T', 6000);
    CHECK(currentState == STATE_PATROLLING && servoAngle == 90);
    CHECK(cctvServo.updateCalls == 0); // No unsigned-underflow early update.
    fakeIoCost = 0;
  } else if (!std::strcmp(test, "lcd_transition")) {
    tick(1999); CHECK(lcd.lines[0] == "Hello World");
    tick(2000); CHECK(lcd.lines[0] == "CCTV Siap!      " && lcd.lines[1] == "MENUNGGU DATA   ");
    const int writes = lcd.writes; tick(2500); CHECK(lcd.writes == writes && adcCalls == 0);
    status('V', 1, 2600);
    CHECK(lcd.lines[0] == " TERDETEKSI APD " && lcd.lines[1] == " TIDAK LENGKAP  ");
    const int alarmWrites = lcd.writes;
    tick(3099); CHECK(lcd.writes == alarmWrites);
    tick(3100); CHECK(lcd.lines[0] == std::string(16, ' ') && lcd.lines[1] == std::string(16, ' '));
    tick(3600); CHECK(lcd.lines[0] == " TERDETEKSI APD ");
  } else if (!std::strcmp(test, "masks")) {
    for (int mask = 1; mask <= 7; ++mask) {
      const unsigned long base = 5000 + mask * 2000;
      status('V', mask, base);
      std::vector<int> items;
      for (int bit = 1; bit <= 4; bit <<= 1) if (mask & bit) items.push_back(bit);
      for (int slot = 0; slot <= 3; ++slot) {
        tick(base + slot * 500);
        int selected = items.size() == 1 ? (slot % 2 ? 0 : items[0]) : items[slot % items.size()];
        CHECK(lamps(bool(selected & 1), bool(selected & 2), bool(selected & 4)));
        CHECK(levels[10] == RELAY_AKTIF && currentState == STATE_LOCKED_ALARM);
      }
    }
  } else if (!std::strcmp(test, "heartbeat")) {
    status('V', 3, 5000);
    const int step = sirineStep;
    for (unsigned long t = 5100; t <= 5499; t += 100) status('V', 3, t);
    CHECK(sirineStep == step && lamps(1, 0, 0));
    status('V', 3, 5500); CHECK(lamps(0, 1, 0));
    status('V', 3, 5820); CHECK(frequency == 0);
    status('V', 3, 6000); CHECK(lamps(1, 0, 0) && frequency == 750);
    status('V', 4, 6100); CHECK(lamps(0, 0, 1)); // Item change resets animation only.
  } else if (!std::strcmp(test, "unknown_fault")) {
    status('U', 0, 100); CHECK(currentState == STATE_MONITOR_FAULT && levels[10] == RELAY_MATI);
    CHECK(lcd.lines[0] == "APD BELUM PASTI ");
    status('V', 3, 5000); status('U', 0, 5500);
    CHECK(currentState == STATE_LOCKED_ALARM && missingPpeMask == 3 && levels[10] == RELAY_AKTIF);
    CHECK(lcd.lines[0] == "APD BELUM PASTI " && lcd.lines[1] == "ALARM DITAHAN   ");
    status('F', 0, 5600);
    CHECK(currentState == STATE_MONITOR_FAULT && levels[10] == RELAY_MATI && frequency == 0 && !cctvServo.isMoving());
    CHECK(lcd.lines[0] == "GANGGUAN SISTEM " && lamps(0, 0, 0));
    status('C', 0, 5700); tick(5800);
    CHECK(currentState == STATE_IDLE_STANDBY && lcd.lines[0] == "APD LENGKAP     ");
    status('N', 0, 5900); CHECK(lcd.lines[0] == "AREA KOSONG     ");
  } else if (!std::strcmp(test, "timeout")) {
    status('V', 7, 5000); tick(7999); CHECK(currentState == STATE_LOCKED_ALARM);
    tick(8000); CHECK(currentState == STATE_MONITOR_FAULT && levels[10] == RELAY_MATI && frequency == 0);
    tick(90000); CHECK(currentState == STATE_MONITOR_FAULT); // Never auto patrol on loss.
    status('N', 0, 90001); tick(90021); CHECK(currentState == STATE_IDLE_STANDBY);
  } else if (!std::strcmp(test, "malformed")) {
    bytes("!PPE,V,3*00\n", 100); CHECK(currentState == STATE_IDLE_STANDBY);
    bytes("!PPE,V,9*00\n!PPE,C,1*00\n!PPE,Q,0*00\n", 200);
    CHECK(currentState == STATE_IDLE_STANDBY && !ppeLinkActive);
    bytes("!garbage1010ATRATRATRATRATRATRATR\n", 300);
    CHECK(currentState == STATE_IDLE_STANDBY && levels[10] == RELAY_MATI && !relayTestActive);
    bytes("!PPE,", 400); bytes("1TR0", 700); bytes("\n", 701);
    CHECK(currentState == STATE_IDLE_STANDBY && cctvServo.targets.empty());
    status('V', 3, 5000); bytes("!PPE,N,0*00\n", 6000);
    CHECK(currentState == STATE_LOCKED_ALARM && lastPpePacketMillis == 5000);
    tick(8000); CHECK(currentState == STATE_MONITOR_FAULT);
    status('V', 1, 8100); CHECK(currentState == STATE_LOCKED_ALARM && missingPpeMask == 1);
  } else if (!std::strcmp(test, "bounded_uart")) {
    Serial.pending = std::string(80, '?'); tick(100);
    CHECK(Serial.available() == 48); tick(101); CHECK(Serial.available() == 16);
    tick(102); CHECK(Serial.available() == 0 && adcCalls == 0);
  } else if (!std::strcmp(test, "alarm_during_boot")) {
    status('V', 1, 100);
    CHECK(lcd.lines[0] == " TERDETEKSI APD " && levels[10] == RELAY_AKTIF);
    tick(600); CHECK(lcd.lines[0] == std::string(16, ' '));
  } else if (!std::strcmp(test, "empty_heartbeat_patrol")) {
    status('N', 0, 100);
    for (unsigned long t = 200; t <= 85000; t += 100) status('N', 0, t);
    CHECK((cctvServo.completed == std::vector<int>{90, 0, 130, 0, 130, 90}));
    CHECK(currentState == STATE_IDLE_STANDBY && ppeLinkActive && ppeObservation == 'N');
  } else if (!std::strcmp(test, "wire_vectors")) {
    WIRE_VECTOR_CHECKS
  } else if (!std::strcmp(test, "serial_ignored")) {
    send('\n', 1000); send('?', 1001);
    CHECK(currentState == STATE_IDLE_STANDBY && levels[10] == RELAY_MATI && lamps(0, 0, 0));
  } else { CHECK(false); }
  CHECK(delayCalls == 0);
  return 0;
}
'''


class LegacyReceiverFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        zig = ROOT / ".tools/ziglang-0.13.0/ziglang/zig.exe"
        cxx = shutil.which("g++") or shutil.which("clang++")
        if cxx:
            compiler = [cxx]
        elif zig.exists():
            compiler = [str(zig), "c++"]
        else:
            raise unittest.SkipTest("A C++17 compiler or the local Zig runtime is needed")
        cls.temp = tempfile.TemporaryDirectory(prefix="apd_receiver_host_")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        for name, text in {"Arduino.h": ARDUINO, "Wire.h": WIRE, "ServoEasing.hpp": SERVO,
                           "LiquidCrystal_PCF8574.h": LCD}.items():
            (folder / name).write_text(text, encoding="utf-8")
        harness = folder / "test.cpp"
        harness.write_text(HARNESS.replace("SKETCH_PATH", SKETCH.as_posix()), encoding="utf-8")
        import sys
        sys.path.insert(0, str(ROOT / "python"))
        from apd_runtime.ppe_bridge import encode_status
        import json
        checks = []
        for state, mask in [("V", m) for m in range(1, 8)] + [(s, 0) for s in "CNUF"]:
            wire = json.dumps(encode_status(state, mask).decode("ascii"))
            checks.append(f"bytes({wire}, 5000); CHECK(ppeObservation == '{state}');")
        harness.write_text(HARNESS.replace("SKETCH_PATH", SKETCH.as_posix()).replace("WIRE_VECTOR_CHECKS", "\n".join(checks)), encoding="utf-8")
        exe = folder / "receiver.exe"
        args = compiler + ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(folder), str(harness), "-o", str(exe)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.executable = exe

    def run_case(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lcd_blink_and_no_adc(self): self.run_case("lcd_transition")
    def test_all_seven_missing_item_combinations(self): self.run_case("masks")
    def test_heartbeat_preserves_animation_and_siren(self): self.run_case("heartbeat")
    def test_unknown_latch_fault_and_recovery(self): self.run_case("unknown_fault")
    def test_camera_link_timeout_locks_servo_and_cuts_audio(self): self.run_case("timeout")
    def test_malformed_overflow_partial_frames_cannot_execute_legacy(self): self.run_case("malformed")
    def test_uart_work_is_bounded(self): self.run_case("bounded_uart")
    def test_alarm_preempts_boot_screen(self): self.run_case("alarm_during_boot")
    def test_no_person_heartbeats_do_not_cancel_auto_patrol(self): self.run_case("empty_heartbeat_patrol")
    def test_python_packets_consumed_by_actual_firmware(self): self.run_case("wire_vectors")
    def test_boot_lcd_and_pin_map(self): self.run_case("boot")
    def test_idle_indicators_off(self): self.run_case("traffic")
    def test_animated_generic_alarm_and_legacy_audio(self): self.run_case("alarm")
    def test_uart_interrupts_nonblocking_servo_return(self): self.run_case("return_interrupt")
    def test_repeated_safe_commands_do_not_stall_return(self): self.run_case("return_repeated_safe")
    def test_relay_test_keeps_traffic_running(self): self.run_case("relay_test")
    def test_alarm_preempts_relay_test(self): self.run_case("relay_alarm_priority")
    def test_patrol_and_return_to_center(self): self.run_case("patrol")
    def test_manual_patrol_exact_sequence(self): self.run_case("manual_patrol")
    def test_repeated_patrol_does_not_restart_easing(self): self.run_case("repeated_patrol")
    def test_cubic_profile_cadence_and_actual_completion(self): self.run_case("cubic_and_cadence")
    def test_patrol_from_locked_angle_centers_without_snap(self): self.run_case("patrol_restart_off_center")
    def test_alarm_cancels_all_remaining_waypoints(self): self.run_case("alarm_cancels_remaining_patrol")
    def test_safe_cancels_all_remaining_waypoints(self): self.run_case("safe_cancels_patrol")
    def test_servo_patrol_across_millis_rollover(self): self.run_case("patrol_rollover")
    def test_missing_lcd_does_not_stop_receiver(self): self.run_case("missing_lcd")
    def test_millis_rollover(self): self.run_case("rollover")
    def test_command_time_advance_cannot_trigger_patrol_or_early_update(self): self.run_case("command_clock_advance")
    def test_unknown_and_newline_serial_ignored(self): self.run_case("serial_ignored")


if __name__ == "__main__":
    unittest.main()
