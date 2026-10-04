/*
 * Proyek Sekolah: Sensor Pengecek Siap APD (Alat Pelindung Diri)
 * File: blink_test.ino
 * Tujuan: Menguji apakah Arduino Uno yang lama tidak dipakai (4 tahun) masih bekerja normal.
 */

const int ledPin = 13; // LED bawaan pada Arduino Uno (terhubung ke pin 13)

void setup() {
  pinMode(ledPin, OUTPUT);
  Serial.begin(9600);
  Serial.println("=== Tes Arduino Uno Siap APD Dimulai ===");
  Serial.println("Jika kamu membaca pesan ini, chip serial & Arduino berfungsi normal!");
}

void loop() {
  digitalWrite(ledPin, HIGH);   // Nyalakan LED
  Serial.println("Status: LED ON (Indikator Aktif)");
  delay(1000);                  // Tunggu 1 detik

  digitalWrite(ledPin, LOW);    // Matikan LED
  Serial.println("Status: LED OFF");
  delay(1000);                  // Tunggu 1 detik
}
