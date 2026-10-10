/*
 * Proyek: Sensor Pengecek Siap APD
 * File: apd_receiver.ino
 * Versi: 1.9 - Relay 1 Channel di Pin 10 (Kendali Daya TPA3110 12V)
 *
 * Perilaku Sistem:
 *   1. POSISI NORMAL (IDLE):
 *      - Relay OFF (Pin 10 LOW) -> TPA3110 tidak mendapat daya -> senyap
 *      - Servo diam di 90 derajat.
 *      - Timer 1 menit mulai menghitung mundur.
 *
 *   2. PATROLI (SETIAP 1 MENIT):
 *      - Relay masih OFF.
 *      - Servo berputar perlahan 0 - 130 derajat.
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

#include <Servo.h>

// === Konfigurasi Pin ===
const int PIN_RELAY   = 10;  // IN relay 1 channel -> COM ke 12V, NO ke VCC TPA3110
const int PIN_AUDIO   = 9;   // Audio tone ke pin R TPA3110
const int PIN_LED_EXT = 8;   // LED Indikator 3V (via Resistor 1k)
const int PIN_SERVO   = 11;  // Signal Oranye Servo SG90
const int PIN_BUILTIN = 13;  // LED internal Arduino

// === Konfigurasi Relay ===
// Ganti HIGH <-> LOW jika relay kamu Active Low (kebanyakan modul relay China aktif LOW)
const int RELAY_AKTIF = HIGH; // Relay ON  -> NO menutup  -> TPA3110 DAPAT DAYA
const int RELAY_MATI  = LOW;  // Relay OFF -> NO terbuka  -> TPA3110 MATI TOTAL

// === Konfigurasi Servo SG90 ===
Servo cctvServo;
const int SUDUT_NORMAL = 90;
const int SUDUT_MIN    = 0;
const int SUDUT_MAX    = 130;

int servoAngle      = SUDUT_NORMAL;
int patrolDirection = 1; // +1 = arah ke 130, -1 = arah ke 0
unsigned long prevPatrolStepMillis = 0;
const int PATROL_STEP_DELAY = 45; // ms per 1 derajat (lebih besar = lebih lambat & kamera lebih stabil)

// === Timer Patroli (1 Menit) ===
const unsigned long PATROL_INTERVAL = 60000UL;
unsigned long lastIdleTimer = 0;

// === State Machine Sistem ===
enum SystemState {
  STATE_IDLE_STANDBY, // Diam di 90°, tunggu 1 menit
  STATE_PATROLLING,   // Sedang putar 0° - 130° cari orang
  STATE_LOCKED_ALARM  // Kunci sudut, relay ON, alarm + LED kedip
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

// Nyalakan suara + kedip LED (Relay sudah harus ON sebelum ini dipanggil)
void playSound(int freq) {
  if (freq > 0) {
    tone(PIN_AUDIO, freq);
    digitalWrite(PIN_LED_EXT, HIGH);
    digitalWrite(PIN_BUILTIN, HIGH);
  } else {
    noTone(PIN_AUDIO);
    digitalWrite(PIN_AUDIO, LOW);
    digitalWrite(PIN_LED_EXT, LOW);
    digitalWrite(PIN_BUILTIN, LOW);
  }
}

// Matikan suara dan LED (Relay terpisah diatur di tempat lain)
void stopSound() {
  noTone(PIN_AUDIO);
  digitalWrite(PIN_AUDIO, LOW);
  digitalWrite(PIN_LED_EXT, LOW);
  digitalWrite(PIN_BUILTIN, LOW);
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

// Servo halus kembali ke 90 derajat
void returnToNormalPosition() {
  while (servoAngle != SUDUT_NORMAL) {
    if (servoAngle < SUDUT_NORMAL) servoAngle++;
    else servoAngle--;
    cctvServo.write(servoAngle);
    delay(20);
  }
}

void setup() {
  pinMode(PIN_RELAY,   OUTPUT);
  pinMode(PIN_AUDIO,   OUTPUT);
  pinMode(PIN_LED_EXT, OUTPUT);
  pinMode(PIN_BUILTIN, OUTPUT);

  // Kondisi awal: semua mati
  relayOff();

  cctvServo.attach(PIN_SERVO);
  servoAngle = SUDUT_NORMAL;
  cctvServo.write(servoAngle);

  Serial.begin(9600);
  delay(300);
  lastIdleTimer = millis();
  Serial.println("READY - APD Receiver v1.9 [Relay Pin10 + Smart CCTV Patrol]");
}

void loop() {
  unsigned long currentMillis = millis();

  // ============================================================
  // 1. TERIMA PERINTAH DARI PYTHON VIA SERIAL
  // ============================================================
  if (Serial.available() > 0) {
    char cmd = Serial.read();

    if (cmd == '1' || cmd == 'A') {
      // PELANGGARAN APD TERDETEKSI:
      // Relay ON (TPA3110 mendapat daya), kunci servo, mulai alarm
      relayOn();
      currentState = STATE_LOCKED_ALARM;
      sirineStep = 0;
      prevAlarmMillis = 0;
      Serial.print("RELAY_ON + LOCKED_AT_ANGLE:");
      Serial.println(servoAngle);
      Serial.println("STATUS:ALARM_ON");

    } else if (cmd == '0' || cmd == 'S') {
      // APD LENGKAP / ORANG PERGI:
      // Relay OFF (TPA3110 mati total), servo kembali ke 90, reset timer
      relayOff();
      returnToNormalPosition();
      currentState = STATE_IDLE_STANDBY;
      lastIdleTimer = millis();
      Serial.println("STATUS:SAFE_RELAY_OFF_RETURN_90");

    } else if (cmd == 'T' || cmd == 't') {
      // Paksa patroli sekarang (tanpa nunggu 1 menit - untuk tes cepat)
      relayOff();
      currentState = STATE_PATROLLING;
      servoAngle = SUDUT_MIN;
      patrolDirection = 1;
      cctvServo.write(servoAngle);
      prevPatrolStepMillis = currentMillis;
      Serial.println("STATUS:MANUAL_PATROL_START");

    } else if (cmd == 'R' || cmd == 'r') {
      // Tes relay saja (untuk keperluan diagnosa)
      relayOn();
      Serial.println("STATUS:RELAY_TEST_ON");
      delay(3000);
      relayOff();
      Serial.println("STATUS:RELAY_TEST_OFF");
    }
  }

  // ============================================================
  // 2. LOGIKA STATE MACHINE
  // ============================================================

  // STATE A: IDLE STANDBY (90 derajat, menunggu 1 menit)
  if (currentState == STATE_IDLE_STANDBY) {
    if (currentMillis - lastIdleTimer >= PATROL_INTERVAL) {
      currentState = STATE_PATROLLING;
      servoAngle = SUDUT_MIN;
      patrolDirection = 1;
      cctvServo.write(servoAngle);
      prevPatrolStepMillis = currentMillis;
      Serial.println("STATUS:PATROL_AUTO_START");
    }
  }

  // STATE B: PATROLLING (0 - 130 derajat memindai)
  else if (currentState == STATE_PATROLLING) {
    if (currentMillis - prevPatrolStepMillis >= (unsigned long)PATROL_STEP_DELAY) {
      prevPatrolStepMillis = currentMillis;
      servoAngle += patrolDirection;
      cctvServo.write(servoAngle);

      if (servoAngle >= SUDUT_MAX) {
        patrolDirection = -1;
      } else if (servoAngle <= SUDUT_MIN && patrolDirection == -1) {
        // Selesai 1 siklus patroli, kembali ke 90 dan tunggu 1 menit lagi
        returnToNormalPosition();
        currentState = STATE_IDLE_STANDBY;
        lastIdleTimer = millis();
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
}
