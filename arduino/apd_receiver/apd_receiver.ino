/*
 * Proyek: Sensor Pengecek Siap APD
 * File: apd_receiver.ino
 * Versi: 1.8 - Sistem Patroli CCTV Cerdas (Auto-Scan 1 Menit, Lock-On & Alarm Sinkron)
 *
 * Perilaku Sistem:
 *   1. POSISI NORMAL (IDLE):
 *      - Servo diam di 90 derajat (menghadap lurus).
 *      - Timer 1 menit (60 detik) mulai menghitung mundur.
 *
 *   2. PATROLI CARI ORANG (SETIAP 1 MENIT):
 *      - Servo berputar perlahan memindai dari 0 hingga 130 derajat.
 *
 *   3. TARGET TERDETEKSI TANPA APD (PERINTAH '1'):
 *      - Servo LANGSUNG BERHENTI / MENGUNCI posisi sudut saat itu juga!
 *      - Alarm TOA "TEET!" (750Hz) berbunyi & LED Pin 8 berkedip sinkron.
 *
 *   4. APD DIPASANG ATAU ORANG PERGI (PERINTAH '0'):
 *      - Alarm & LED langsung MATI SEKETIKA.
 *      - Servo berputar kembali ke posisi normal (90 derajat).
 *      - Timer 1 menit di-reset dari awal untuk patroli berikutnya.
 */

#include <Servo.h>

// === Konfigurasi Pin ===
const int PIN_AUDIO   = 9;   // Audio tone ke pin R modul TPA3110 (12V)
const int PIN_LED_EXT = 8;   // LED Indikator 3V (via Resistor 1k)
const int PIN_SERVO   = 11;  // Signal Oranye Servo SG90
const int PIN_BUILTIN = 13;  // LED internal Arduino

// === Konfigurasi Servo SG90 ===
Servo cctvServo;
const int SUDUT_NORMAL = 90;
const int SUDUT_MIN    = 0;
const int SUDUT_MAX    = 130;

int servoAngle = SUDUT_NORMAL;
int patrolDirection = 1;     // +1 naik ke 130, -1 turun ke 0
unsigned long prevPatrolStepMillis = 0;
const int PATROL_STEP_DELAY = 45; // Kecepatan putar patroli (45ms per 1 derajat agar kamera jelas memindai)

// === Timer Patroli (1 Menit) ===
const unsigned long PATROL_INTERVAL = 60000UL; // 60.000 ms = 1 Menit
unsigned long lastIdleTimer = 0;

// === State Machine Sistem ===
enum SystemState {
  STATE_IDLE_STANDBY,  // Diam di 90 derajat, menunggu 1 menit
  STATE_PATROLLING,    // Sedang berputar 0 - 130 derajat mencari orang
  STATE_LOCKED_ALARM   // Mengunci posisi sudut orang & membunyikan alarm
};

SystemState currentState = STATE_IDLE_STANDBY;

// === Pola Horn TOA "TEET!" per 1 Detik ===
// {frekuensi Hz, durasi ms}
const int SIRINE[][2] = {
  { 750, 180 },  // Nada klakson TOA (180ms) + LED NYALA
  {   0, 820 }   // Hening (820ms)           + LED MATI
};
const int TOTAL_STEP = 2;
unsigned long prevAlarmMillis = 0;
int sirineStep = 0;

// Fungsi suara + kedip LED sinkron
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

void stopSound() {
  noTone(PIN_AUDIO);
  digitalWrite(PIN_AUDIO, LOW);
  digitalWrite(PIN_LED_EXT, LOW);
  digitalWrite(PIN_BUILTIN, LOW);
}

// Menggerakkan servo secara halus kembali ke 90 derajat
void returnToNormalPosition() {
  while (servoAngle != SUDUT_NORMAL) {
    if (servoAngle < SUDUT_NORMAL) servoAngle++;
    else if (servoAngle > SUDUT_NORMAL) servoAngle--;
    cctvServo.write(servoAngle);
    delay(20);
  }
}

void setup() {
  pinMode(PIN_AUDIO,   OUTPUT);
  pinMode(PIN_LED_EXT, OUTPUT);
  pinMode(PIN_BUILTIN, OUTPUT);

  stopSound();

  cctvServo.attach(PIN_SERVO);
  servoAngle = SUDUT_NORMAL;
  cctvServo.write(servoAngle); // Posisi awal 90 derajat

  Serial.begin(9600);
  delay(300);
  lastIdleTimer = millis();
  Serial.println("READY - APD Receiver v1.8 [Smart CCTV Patrol & Lock-On]");
}

void loop() {
  unsigned long currentMillis = millis();

  // ============================================================
  // 1. TERIMA PERINTAH DARI AI PYTHON VIA SERIAL
  // ============================================================
  if (Serial.available() > 0) {
    char cmd = Serial.read();

    if (cmd == '1' || cmd == 'A') {
      // PELANGGARAN APD TERDETEKSI:
      // KUNCI POSISI SERVO SAAT INI & BUNYIKAN ALARM
      currentState = STATE_LOCKED_ALARM;
      sirineStep = 0;
      prevAlarmMillis = 0; // Segera bunyikan nada pertama
      Serial.print("LOCKED_AT_ANGLE:");
      Serial.println(servoAngle);
      Serial.println("STATUS:ALARM_ON");

    } else if (cmd == '0' || cmd == 'S') {
      // APD SUDAH DIPASANG / ORANG HILANG DARI KAMERA:
      // Matikan alarm, kembali ke 90 derajat, reset timer 1 menit
      if (currentState == STATE_LOCKED_ALARM || currentState == STATE_PATROLLING) {
        stopSound();
        returnToNormalPosition();
        currentState = STATE_IDLE_STANDBY;
        lastIdleTimer = millis(); // Reset timer 1 menit
        Serial.println("STATUS:SAFE_RETURN_TO_90");
      }

    // Perintah manual paksa patroli sekarang (untuk pengujian cepat tanpa nunggu 1 menit)
    } else if (cmd == 'T' || cmd == 't') {
      stopSound();
      currentState = STATE_PATROLLING;
      servoAngle = SUDUT_MIN;
      patrolDirection = 1;
      cctvServo.write(servoAngle);
      Serial.println("STATUS:MANUAL_PATROL_START");
    }
  }

  // ============================================================
  // 2. LOGIKA STATE MACHINE
  // ============================================================

  // --- STATE A: IDLE STANDBY (Menunggu di 90 Derajat selama 1 Menit) ---
  if (currentState == STATE_IDLE_STANDBY) {
    if (currentMillis - lastIdleTimer >= PATROL_INTERVAL) {
      // Waktu 1 menit habis -> Mulai patroli memindai dari 0 ke 130 derajat
      currentState = STATE_PATROLLING;
      servoAngle = SUDUT_MIN;
      patrolDirection = 1;
      cctvServo.write(servoAngle);
      prevPatrolStepMillis = currentMillis;
      Serial.println("STATUS:PATROL_START_0_TO_130");
    }
  }

  // --- STATE B: PATROLLING (Memutar dari 0 ke 130 Derajat mencari orang) ---
  else if (currentState == STATE_PATROLLING) {
    if (currentMillis - prevPatrolStepMillis >= (unsigned long)PATROL_STEP_DELAY) {
      prevPatrolStepMillis = currentMillis;

      servoAngle += patrolDirection;
      cctvServo.write(servoAngle);

      // Jika sudah mencapai 130 derajat, putar balik ke 0
      if (servoAngle >= SUDUT_MAX) {
        patrolDirection = -1;
      } 
      // Jika sudah kembali ke 0 derajat, selesai 1 siklus patroli -> Kembali ke 90 & tunggu 1 menit lagi
      else if (servoAngle <= SUDUT_MIN && patrolDirection == -1) {
        returnToNormalPosition();
        currentState = STATE_IDLE_STANDBY;
        lastIdleTimer = millis();
        Serial.println("STATUS:PATROL_FINISHED_RESET_1_MIN");
      }
    }
  }

  // --- STATE C: LOCKED ALARM (Orang Terkunci: Bunyikan TOA + LED Kedip Sinkron) ---
  else if (currentState == STATE_LOCKED_ALARM) {
    // Servo tetap diam di sudut terkunci (tidak digerakkan)
    int durasi = SIRINE[sirineStep][1];

    if (currentMillis - prevAlarmMillis >= (unsigned long)durasi) {
      prevAlarmMillis = currentMillis;
      playSound(SIRINE[sirineStep][0]);
      sirineStep = (sirineStep + 1) % TOTAL_STEP;
    }
  }
}
