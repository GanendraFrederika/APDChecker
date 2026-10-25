/*
 * Proyek: Sensor Pengecek Siap APD
 * File: apd_receiver.ino
 * Versi: 2.2 - Indikator APD per item + LCD 500 ms + status kamera ber-checksum
 *
 * Perilaku Sistem:
 *   1. POSISI NORMAL (IDLE):
 *      - Relay OFF (Pin 10 LOW) -> TPA3110 tidak mendapat daya -> senyap
 *      - Servo diam di 90 derajat.
 *      - Timer 1 menit mulai menghitung mundur.
 *
 *   2. PATROLI (SETIAP 1 MENIT):
 *      - Relay masih OFF.
 *      - Servo halus 90 -> 0 -> 130 -> 0 -> 130 -> 90 derajat.
 *
 *   3. TARGET TERDETEKSI TANPA APD (PERINTAH '1'):
 *      - Relay ON (Pin 10 HIGH) -> NO menutup -> 12V masuk TPA3110 -> speaker bunyi!
 *      - Servo LANGSUNG BERHENTI / MENGUNCI.
 *      - Alarm TOA "TEET!" (750Hz) + LED Pin 8 kedip sinkron.
 *
 *   4. APD DIPASANG / ORANG PERGI (PERINTAH '0'):
 *      - Relay OFF (Pin 10 LOW) -> TPA3110 mati total -> senyap.
 *      - LED langsung mati.
 *      - Servo halus balik ke 90 derajat.
 *      - Timer 1 menit di-reset.
 *
 * Catatan Relay:
 *   - Modul relay 1ch umumnya ACTIVE HIGH (HIGH = relay aktif / NO menutup)
 *   - Jika relay kamu ACTIVE LOW (nyala saat LOW), tukar RELAY_AKTIF & RELAY_MATI di bawah
 */

// Cukup easing cubic dan satu servo pan; tilt D7 tetap belum diaktifkan.
#define ENABLE_EASE_CUBIC
#define MAX_EASING_SERVOS 1
#include <ServoEasing.hpp>
#include <Wire.h>
#include <LiquidCrystal_PCF8574.h>
#include <stdio.h>
#include <string.h>

// === Konfigurasi Pin Arduino Uno (rancangan terbaru) ===
// D0/RX dan D1/TX: UART Luckfox, 9600 baud. Jangan dipakai untuk fungsi lain.
const int PIN_DS18B20_ARDUINO = 2;  // Reserved: data sensor suhu Arduino
const int PIN_DS18B20_PICO    = 3;  // Reserved: data sensor suhu Pico
const int ind_helm_m         = 4;  // LED merah (aktif HIGH, gunakan resistor)
const int PIN_KIPAS_PICO     = 5;  // Reserved: gate MOSFET kipas kamera & Pico
const int PIN_KIPAS_ARDUINO  = 6;  // Reserved: gate MOSFET kipas Arduino
const int PIN_SERVO_TILT     = 7;  // Reserved: servo naik-turun, belum di-attach
const int PIN_LED_EXT        = 8;  // LED alarm, tetap sinkron dengan suara
const int PIN_AUDIO          = 9;  // Audio tone ke input TPA3110
const int PIN_RELAY          = 10; // IN relay daya TPA3110 (perilaku lama tetap)
const int PIN_SERVO          = 11; // Servo kanan-kiri / pan yang sudah dipakai
const int ind_rompi_h        = 12; // LED hijau
// D13 tidak digunakan, termasuk LED builtin.
const int ind_sepatu_k       = A0; // LED kuning; A0 dipakai sebagai output digital
// A1 tidak digunakan: tidak ada pembacaan baterai, biarkan kabel A1 terlepas.
// A2-A3 kosong. A4/SDA dan A5/SCL khusus LCD I2C melalui Wire.

// === LCD 16x2 dengan backpack PCF8574 ===
// Library: LiquidCrystal_PCF8574 by Matthias Hertel (bukan LiquidCrystal_I2C).
// Sesuaikan alamat dengan backpack fisik; 0x27 adalah asumsi awal, bukan hasil ukur.
const uint8_t LCD_I2C_ADDRESS = 0x27;
LiquidCrystal_PCF8574 lcd(LCD_I2C_ADDRESS);
bool lcdAvailable = false;
unsigned long lcdBootMillis = 0;
const unsigned long LCD_BOOT_DURATION = 2000UL;
char lastLcdLines[2][17] = {"", ""};

// Tidak ada pembacaan baterai. A1 dibiarkan tidak terhubung.
// Bit mask: 1=helm/merah, 2=sepatu/kuning, 4=rompi/hijau.
const uint8_t PPE_HELMET = 1;
const uint8_t PPE_SHOES = 2;
const uint8_t PPE_VEST = 4;
const unsigned long PPE_ANIMATION_INTERVAL = 500UL;
const unsigned long PPE_LINK_TIMEOUT = 3000UL;
char ppeObservation = 'W'; // W=menunggu, V=pelanggaran, C=lengkap, N=kosong, U=unknown, F=fault
uint8_t missingPpeMask = 0;
char animationObservation = '?';
uint8_t animationMask = 0xff;
unsigned long prevAnimationMillis = 0;
uint8_t animationStep = 0;
bool animationVisible = true;
bool ppeLinkActive = false;
unsigned long lastPpePacketMillis = 0;
// Parser terpisah: isi frame rusak TIDAK boleh bocor menjadi perintah legacy 1/0/T/R.
char ppeRx[17];
uint8_t ppeRxLength = 0;
bool ppeRxActive = false;
bool ppeRxDiscard = false;
unsigned long lastPpeRxMillis = 0;
const unsigned long PPE_RX_TIMEOUT = 250UL;

// === Konfigurasi Relay ===
// Ganti HIGH <-> LOW jika relay kamu Active Low (kebanyakan modul relay China aktif LOW)
const int RELAY_AKTIF = HIGH; // Relay ON  -> NO menutup  -> TPA3110 DAPAT DAYA
const int RELAY_MATI  = LOW;  // Relay OFF -> NO terbuka  -> TPA3110 MATI TOTAL

// === Konfigurasi Servo SG90: pan D11 ===
ServoEasing cctvServo;
const int SUDUT_NORMAL = 90;
const int SUDUT_MIN    = 0;
const int SUDUT_MAX    = 130;
// Kecepatan rata-rata, bukan kecepatan puncak kurva cubic. Lebih kecil = lambat.
const uint_fast16_t PATROL_SPEED_DPS = 22;
const uint_fast16_t RETURN_SPEED_DPS = 30;
const unsigned long SERVO_UPDATE_INTERVAL = 20UL;
unsigned long prevServoUpdateMillis = 0;
int servoAngle = SUDUT_NORMAL; // Posisi perintah terakhir, BUKAN feedback encoder.
const int PATROL_WAYPOINTS[] = {
  SUDUT_NORMAL, SUDUT_MIN, SUDUT_MAX, SUDUT_MIN, SUDUT_MAX, SUDUT_NORMAL
};
const uint8_t PATROL_WAYPOINT_COUNT = sizeof(PATROL_WAYPOINTS) / sizeof(PATROL_WAYPOINTS[0]);
uint8_t patrolWaypointIndex = 0;

// === Timer Patroli (1 Menit) ===
const unsigned long PATROL_INTERVAL = 60000UL;
unsigned long lastIdleTimer = 0;

// === State Machine Sistem ===
enum SystemState {
  STATE_IDLE_STANDBY, // Diam di 90°, tunggu 1 menit
  STATE_PATROLLING,   // Waypoint 90 -> 0 -> 130 -> 0 -> 130 -> 90
  STATE_LOCKED_ALARM, // Kunci sudut, relay ON, alarm + LED kedip
  STATE_RETURNING_NORMAL, // Kembali ke 90 tanpa menghentikan UART/lampu
  STATE_MONITOR_FAULT // Lock posisi, relay/audio OFF; bukan SAFE
};
SystemState currentState = STATE_IDLE_STANDBY;

// === Pola Horn TOA ===
// {frekuensi Hz (0 = hening), durasi ms}
const int SIRINE[][2] = {
  { 750, 180 }, // Nada klakson TOA 180ms -> Relay sudah ON, speaker berbunyi, LED NYALA
  {   0, 820 }  // Hening 820ms             -> Suara off, LED MATI (relay tetap ON)
};
const int TOTAL_STEP = 2;
unsigned long prevAlarmMillis = 0;
int sirineStep = 0;
bool relayTestActive = false;
unsigned long relayTestStartedMillis = 0;
const unsigned long RELAY_TEST_DURATION = 3000UL;

// Nyalakan suara + kedip LED (Relay sudah harus ON sebelum ini dipanggil)
void playSound(int freq) {
  if (freq > 0) {
    tone(PIN_AUDIO, freq);
    digitalWrite(PIN_LED_EXT, HIGH);
  } else {
    noTone(PIN_AUDIO);
    digitalWrite(PIN_AUDIO, LOW);
    digitalWrite(PIN_LED_EXT, LOW);
  }
}

// Matikan suara dan LED (Relay terpisah diatur di tempat lain)
void stopSound() {
  noTone(PIN_AUDIO);
  digitalWrite(PIN_AUDIO, LOW);
  digitalWrite(PIN_LED_EXT, LOW);
}

// Relay ON: TPA3110 mendapat daya 12V
void relayOn() {
  digitalWrite(PIN_RELAY, RELAY_AKTIF);
}

// Relay OFF: TPA3110 mati total (tidak ada suara dengung sama sekali)
void relayOff() {
  stopSound();
  digitalWrite(PIN_RELAY, RELAY_MATI);
}

// setEaseTo() hanya menjadwalkan gerak; jangan pakai easeTo() yang blocking.
// Update di loop, tanpa timer easing tambahan dan tanpa write integer 1 derajat.
void beginServoMove(int target, uint_fast16_t speedDps) {
  cctvServo.setEaseTo(target, speedDps);
  prevServoUpdateMillis = millis();
}

void updateServoMotion(unsigned long now) {
  if (cctvServo.isMoving() && now - prevServoUpdateMillis >= SERVO_UPDATE_INTERVAL) {
    prevServoUpdateMillis = now;
    cctvServo.update();
    servoAngle = cctvServo.read();
  }
}

// Stop mempertahankan pulsa terakhir dan tetap attach: tidak meloncat ke target.
void lockServoPosition() {
  cctvServo.stop();
  servoAngle = cctvServo.read();
}

void startPatrol() {
  // Perintah T berulang tidak boleh terus me-reset kurva/urutan.
  if (currentState == STATE_PATROLLING) return;
  relayTestActive = false;
  relayOff();
  lockServoPosition();
  currentState = STATE_PATROLLING;
  patrolWaypointIndex = 0;
  // Dari sudut selain 90, pulang ke 90 secara halus sebelum memulai urutan.
  beginServoMove(PATROL_WAYPOINTS[patrolWaypointIndex], PATROL_SPEED_DPS);
}

void returnToNormalPosition() {
  // SAFE berulang dari sender tidak boleh mengulang easing dari awal.
  if (currentState == STATE_RETURNING_NORMAL) return;
  if (currentState == STATE_IDLE_STANDBY && !cctvServo.isMoving() && servoAngle == SUDUT_NORMAL) {
    lastIdleTimer = millis();
    return;
  }
  lockServoPosition();
  currentState = STATE_RETURNING_NORMAL;
  beginServoMove(SUDUT_NORMAL, RETURN_SPEED_DPS);
}

void initLcd() {
  Wire.begin(); // Uno: SDA=A4, SCL=A5
#ifdef WIRE_HAS_TIMEOUT
  Wire.setWireTimeout(25000UL, true); // Hindari hang jika bus I2C bermasalah
#endif
  Wire.beginTransmission(LCD_I2C_ADDRESS);
  if (Wire.endTransmission() != 0) {
    Serial.println(F("WARN:LCD_NOT_FOUND_CHECK_ADDRESS_AND_WIRING"));
    return; // LCD tidak ada: UART, relay, servo, dan debug tetap berjalan
  }
  lcd.begin(16, 2);
  lcd.setBacklight(255);
  lcd.setCursor(0, 0);
  lcd.print(F("Hello World"));
  lcd.setCursor(0, 1);
  lcd.print(F("Inisialisasi..."));
  lcdAvailable = true;
  lcdBootMillis = millis();
}

// Cache 16 kolom: tidak memakai lcd.clear() berulang yang menambah flicker.
void writeLcdRow(uint8_t row, const char *text) {
  char padded[17];
  uint8_t n = strlen(text);
  if (n > 16) n = 16;
  memcpy(padded, text, n);
  for (uint8_t i = n; i < 16; ++i) padded[i] = ' ';
  padded[16] = '\0';
  if (strcmp(lastLcdLines[row], padded) != 0) {
    lcd.setCursor(0, row);
    lcd.print(padded);
    strcpy(lastLcdLines[row], padded);
  }
}

void updatePpeIndicators(unsigned long now) {
  if (animationObservation != ppeObservation || animationMask != missingPpeMask) {
    animationObservation = ppeObservation;
    animationMask = missingPpeMask;
    prevAnimationMillis = now;
    animationStep = 0;
    animationVisible = true;
  }
  const uint32_t steps = uint32_t(now - prevAnimationMillis) / PPE_ANIMATION_INTERVAL;
  if (steps > 0) {
    prevAnimationMillis += steps * PPE_ANIMATION_INTERVAL;
    if (steps % 2) animationVisible = !animationVisible;
  }
  uint8_t selected = 0;
  if (currentState == STATE_LOCKED_ALARM && missingPpeMask) {
    uint8_t items[3], count = 0;
    for (uint8_t bit = 1; bit <= PPE_VEST; bit <<= 1) {
      if (missingPpeMask & bit) items[count++] = bit;
    }
    if (count == 1) selected = animationVisible ? items[0] : 0;
    else {
      animationStep = (animationStep + steps % count) % count;
      selected = items[animationStep];
    }
  }
  digitalWrite(ind_helm_m, (selected & PPE_HELMET) ? HIGH : LOW);
  digitalWrite(ind_sepatu_k, (selected & PPE_SHOES) ? HIGH : LOW);
  digitalWrite(ind_rompi_h, (selected & PPE_VEST) ? HIGH : LOW);
}

void updateLcd(unsigned long now) {
  if (!lcdAvailable) return;
  if (ppeObservation == 'V') { // Alarm tidak menunggu boot 2 detik.
    writeLcdRow(0, animationVisible ? " TERDETEKSI APD " : "");
    writeLcdRow(1, animationVisible ? " TIDAK LENGKAP " : "");
  } else if (ppeObservation == 'F') {
    writeLcdRow(0, "GANGGUAN SISTEM");
    writeLcdRow(1, "CEK KAMERA/LINK");
  } else if (ppeObservation == 'U') {
    writeLcdRow(0, "APD BELUM PASTI");
    writeLcdRow(1, currentState == STATE_LOCKED_ALARM ? "ALARM DITAHAN" : "CEK KAMERA/MODEL");
  } else if (ppeObservation == 'C') {
    writeLcdRow(0, "APD LENGKAP");
    writeLcdRow(1, "MONITORING AKTIF");
  } else if (ppeObservation == 'N') {
    writeLcdRow(0, "AREA KOSONG");
    writeLcdRow(1, "MONITORING AKTIF");
  } else if (uint32_t(now - lcdBootMillis) >= LCD_BOOT_DURATION) {
    writeLcdRow(0, "CCTV Siap!"); // Hanya MCU siap, bukan konfirmasi AI aman.
    writeLcdRow(1, "MENUNGGU DATA");
  }
}

void enterAlarm(uint8_t mask, bool legacy = false) {
  relayTestActive = false;
  if (currentState != STATE_LOCKED_ALARM || legacy) {
    lockServoPosition();
    relayOn();
    currentState = STATE_LOCKED_ALARM;
    // Timing horn/LED D8 legacy dipertahankan. Heartbeat tidak mereset sirene.
    sirineStep = 0;
    prevAlarmMillis = 0;
  }
  ppeObservation = 'V';
  missingPpeMask = mask;
}

void enterMonitorFault() {
  relayTestActive = false;
  relayOff();
  lockServoPosition();
  currentState = STATE_MONITOR_FAULT;
  ppeObservation = 'F';
  missingPpeMask = 0;
}

int hexDigit(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// !PPE,V,3*HH\n : XOR ASCII body PPE,V,3; 3=helm+sepatu.
// N/C/U/F wajib mask 0. V wajib 1..7. Tidak kompatibel APD3.
bool applyPpePacket(unsigned long now) {
  if (ppeRxLength != 10 || strncmp(ppeRx, "PPE,", 4) != 0 ||
      ppeRx[5] != ',' || ppeRx[7] != '*' || ppeRx[6] < '0' || ppeRx[6] > '7') return false;
  const int hi = hexDigit(ppeRx[8]), lo = hexDigit(ppeRx[9]);
  if (hi < 0 || lo < 0) return false;
  uint8_t checksum = 0;
  for (uint8_t i = 0; i < 7; ++i) checksum ^= uint8_t(ppeRx[i]);
  if (checksum != uint8_t((hi << 4) | lo)) return false;
  const char state = ppeRx[4];
  const uint8_t mask = ppeRx[6] - '0';
  if (state == 'V' ? mask == 0 : mask != 0) return false;
  if (state != 'V' && state != 'C' && state != 'N' && state != 'U' && state != 'F') return false;
  ppeLinkActive = true;
  lastPpePacketMillis = now;
  if (state == 'V') enterAlarm(mask);
  else if (state == 'C' || state == 'N') {
    relayTestActive = false;
    relayOff();
    if (ppeObservation != state || (currentState != STATE_IDLE_STANDBY &&
        currentState != STATE_PATROLLING && currentState != STATE_RETURNING_NORMAL)) returnToNormalPosition();
    ppeObservation = state;
    missingPpeMask = 0;
  } else if (state == 'F') enterMonitorFault();
  else {
    ppeObservation = 'U';
    if (currentState != STATE_LOCKED_ALARM) {
      relayTestActive = false;
      relayOff();
      lockServoPosition();
      currentState = STATE_MONITOR_FAULT;
      missingPpeMask = 0;
    } // UNKNOWN tidak boleh menghapus alarm pelanggaran yang sudah diketahui.
  }
  return true;
}

void handleLegacyCommand(char cmd, unsigned long now) {
  if (cmd == '1' || cmd == 'A') {
    ppeLinkActive = false;
    enterAlarm(7, true); // Alarm generik/manual: semua warna, bukan hasil klasifikasi.
    Serial.print("RELAY_ON + LOCKED_AT_ANGLE:");
    Serial.println(servoAngle);
    Serial.println("STATUS:ALARM_ON");
  } else if (cmd == '0' || cmd == 'S') {
    ppeLinkActive = false;
    ppeObservation = 'W'; // Manual OFF bukan bukti APD lengkap.
    missingPpeMask = 0;
    relayTestActive = false;
    relayOff();
    returnToNormalPosition();
    Serial.println("STATUS:SAFE_RELAY_OFF_RETURN_90");
  } else if (cmd == 'T' || cmd == 't') {
    ppeLinkActive = false;
    ppeObservation = 'W';
    missingPpeMask = 0;
    startPatrol();
    Serial.println("STATUS:MANUAL_PATROL_START");
  } else if (cmd == 'R' || cmd == 'r') {
    if (currentState == STATE_LOCKED_ALARM) Serial.println("STATUS:RELAY_TEST_SKIPPED_ALARM_ACTIVE");
    else {
      relayOn();
      relayTestActive = true;
      relayTestStartedMillis = now;
      Serial.println("STATUS:RELAY_TEST_ON");
    }
  }
}

void receiveCommands(unsigned long now) {
  if (ppeRxActive && uint32_t(now - lastPpeRxMillis) >= PPE_RX_TIMEOUT) {
    // Tetap buang sampai newline / ! baru; ekor frame bukan command legacy.
    ppeRxDiscard = true;
  }
  // Bounded UART work: lampu, LCD, servo dan alarm tetap mendapat giliran.
  for (uint8_t n = 0; n < 32 && Serial.available() > 0; ++n) {
    const char c = Serial.read();
    if (c == '!') {
      ppeRxActive = true;
      ppeRxDiscard = false;
      ppeRxLength = 0;
      lastPpeRxMillis = millis();
    } else if (ppeRxActive) {
      lastPpeRxMillis = millis();
      if (c == '\n') {
        if (!ppeRxDiscard && !applyPpePacket(millis())) Serial.println(F("WARN:PPE_FRAME_REJECTED"));
        ppeRxActive = false;
        ppeRxDiscard = false;
      } else if (c != '\r' && !ppeRxDiscard) {
        if (ppeRxLength < sizeof(ppeRx) - 1) ppeRx[ppeRxLength++] = c;
        else ppeRxDiscard = true;
      }
    } else handleLegacyCommand(c, millis());
  }
}

void setup() {
  pinMode(PIN_RELAY,   OUTPUT);
  pinMode(PIN_AUDIO,   OUTPUT);
  pinMode(PIN_LED_EXT, OUTPUT);
  pinMode(ind_helm_m, OUTPUT);
  pinMode(ind_sepatu_k, OUTPUT);
  pinMode(ind_rompi_h, OUTPUT);
  digitalWrite(ind_helm_m, LOW);
  digitalWrite(ind_sepatu_k, LOW);
  digitalWrite(ind_rompi_h, LOW);
  // Sensor, kipas, dan servo tilt baru dicadangkan; belum dikendalikan di sini.

  // Kondisi awal: semua mati
  relayOff();

  cctvServo.attach(PIN_SERVO, SUDUT_NORMAL);
  cctvServo.setEasingType(EASE_CUBIC_IN_OUT);
  servoAngle = cctvServo.read();

  Serial.begin(9600);
  initLcd();
  lastIdleTimer = millis();
  updatePpeIndicators(millis());
  Serial.println(F("READY - APD Receiver v2.2 [PPE1 LCD 500ms + ServoEasing Cubic Patrol]"));
}

void loop() {
  unsigned long currentMillis = millis();

  if (relayTestActive && currentMillis - relayTestStartedMillis >= RELAY_TEST_DURATION) {
    relayTestActive = false;
    relayOff();
    Serial.println("STATUS:RELAY_TEST_OFF");
  }

  receiveCommands(currentMillis);
  currentMillis = millis();
  if (ppeLinkActive && uint32_t(currentMillis - lastPpePacketMillis) >= PPE_LINK_TIMEOUT) {
    ppeLinkActive = false;
    enterMonitorFault();
    Serial.println(F("WARN:PPE_LINK_TIMEOUT"));
  }

  // ============================================================
  // 2. LOGIKA STATE MACHINE
  // ============================================================

  // Operasi serial dapat memakan waktu; hindari memakai timestamp sebelum perintah.
  currentMillis = millis();
  updateServoMotion(currentMillis); // UART/alarm diproses lebih dulu.

  // STATE A: IDLE STANDBY (90 derajat, menunggu 1 menit)
  if (currentState == STATE_IDLE_STANDBY) {
    if (currentMillis - lastIdleTimer >= PATROL_INTERVAL) {
      startPatrol();
      Serial.println("STATUS:PATROL_AUTO_START");
    }
  }

  // STATE B: tunggu gerak selesai, baru maju ke waypoint berikutnya.
  else if (currentState == STATE_PATROLLING) {
    if (!cctvServo.isMoving()) {
      if (patrolWaypointIndex + 1 < PATROL_WAYPOINT_COUNT) {
        ++patrolWaypointIndex;
        beginServoMove(PATROL_WAYPOINTS[patrolWaypointIndex], PATROL_SPEED_DPS);
      } else {
        currentState = STATE_IDLE_STANDBY;
        lastIdleTimer = currentMillis; // Hitung 60 detik setelah easing ke 90 selesai.
        Serial.println("STATUS:PATROL_DONE_RESET_1_MIN");
      }
    }
  }

  // STATE C: LOCKED ALARM (Relay ON, Servo kunci, Horn TOA + LED kedip)
  else if (currentState == STATE_LOCKED_ALARM) {
    int durasi = SIRINE[sirineStep][1];
    if (currentMillis - prevAlarmMillis >= (unsigned long)durasi) {
      prevAlarmMillis = currentMillis;
      playSound(SIRINE[sirineStep][0]);
      sirineStep = (sirineStep + 1) % TOTAL_STEP;
    }
  }

  // STATE D: balik ke tengah sambil tetap melayani serial dan indikator.
  else if (currentState == STATE_RETURNING_NORMAL) {
    if (!cctvServo.isMoving()) {
      currentState = STATE_IDLE_STANDBY;
      lastIdleTimer = currentMillis;
    }
  }

  updatePpeIndicators(millis());
  updateLcd(millis());
}