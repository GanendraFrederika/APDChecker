# 🔌 Panduan Rangkaian Hardware (Arduino Uno, Speaker & Lampu USB)

Dokumen ini memandu pemasangan kabel pada **Breadboard** dan **Arduino Uno** secara aman agar Arduino tidak rusak akibat beban arus berlebih.

---

## ⚠️ 1. PERINGATAN PENTING: Speaker 4-Inch & Arduino

> **Kenapa Speaker 4-Inch TIDAK Boleh Langsung Dicolok ke Pin Arduino?**
> - Pin digital Arduino Uno hanya sanggup menyediakan arus maksimal **20 - 40 mA**.
> - Speaker 4-inch (impedansi 4Ω atau 8Ω) membutuhkan arus **250 - 1000 mA (0.25A - 1A)** untuk berbunyi normal.
> - Jika dipaksa colok langsung: pin Arduino bisa hangus dan mikrokontroler ATmega328P bisa rusak permanen!

### Solusi Rangkaian untuk Speaker:
1. **Opsi Rekomendasi (Paling Mudah & Murah): Modul Amplifier Mini PAM8403 (Rp 3.000 - Rp 6.000)**
   - VCC PAM8403 ➔ 5V Arduino atau Adaptor USB
   - GND PAM8403 ➔ GND Arduino
   - L/R In ➔ Pin Digital 9 Arduino
   - Speaker Out ➔ 2 Kabel Speaker 4-inch
2. **Opsi Alternatif: Rangkaian Transistor Sederhana (TIP120 / BD139 / 2N2222)**
   - Pin 9 Arduino ➔ Resistor 1kΩ ➔ Basis Transistor
   - Kolektor Transistor ➔ Kabel (-) Speaker
   - Kabel (+) Speaker ➔ 5V Eksternal / 5V Arduino (dengan dioda pengaman 1N4007)
   - Emitor Transistor ➔ GND
3. **Opsi Uji Coba Awal (Tanpa Komponen Tambahan):**
   - Speaker suara sirine/alarm dibunyikan lewat **Speaker Laptop** langsung menggunakan Python, sedangkan pin Arduino digunakan menyalakan lampu indikator dan LED di breadboard.

---

## 💡 2. Rangkaian Lampu Indikator Mini USB

Lampu USB mini biasanya memiliki 4 jalur kabel di dalamnya (atau 2 jalur jika hanya lampu LED strip):
- **Kabel Merah:** Positif (+5V)
- **Kabel Hitam:** Ground (GND / Negatif)
- **Kabel Putih & Hijau:** Jalur data USB (tidak dipakai untuk lampu biasa)

### Cara Menghubungkannya ke Arduino:
- **Metode Relay:**
  - Pin 8 Arduino ➔ Pin IN Modul Relay
  - VCC Relay ➔ 5V Arduino
  - GND Relay ➔ GND Arduino
  - Relay memutus/menyambung jalur kabel Merah (+5V) lampu USB.
- **Metode Breadboard Sederhana (Untuk Uji Coba Pertama):**
  - Gunakan 1 buah lampu LED biasa (Merah) di breadboard.
  - Pin 8 Arduino ➔ Resistor 220Ω / 330Ω ➔ Kaki Anoda (+) LED Merah
  - Kaki Katoda (-) LED Merah ➔ GND Arduino

---

## 📌 3. Ringkasan Peta Pin Arduino Uno

| Komponen | Pin Arduino Uno | Keterangan |
| :--- | :--- | :--- |
| **LED Indikator Internal** | Pin 13 | LED bawaan di papan Arduino |
| **Lampu Indikator (Relay/LED)** | Pin 8 | Output digital (HIGH = Nyala, LOW = Mati) |
| **Speaker Alarm (Audio Tone)** | Pin 9 | Output PWM frekuensi nada sirine |
| **Ground Bersama** | GND | Terhubung ke jalur negatif breadboard |
| **Daya Sensor/Modul** | 5V | Jalur positif daya breadboard |

---

## 🧪 4. Langkah Uji Coba Pertama (Blink Test)

Sebelum memasang rangkaian rumit:
1. Hubungkan Arduino Uno ke laptop dengan kabel USB tipe A-to-B.
2. Buka **Arduino IDE**.
3. Buka file `arduino/blink_test/blink_test.ino`.
4. Di Arduino IDE:
   - Pilih menu **Tools > Board > Arduino Uno**
   - Pilih menu **Tools > Port > COM...** (pilih port Arduino kamu)
5. Klik tombol tanda centang (Verify) lalu tanda panah (Upload).
6. Buka **Serial Monitor** (kecepatan `9600 baud`).
7. Jika lampu kecil di dekat pin 13 berkedip dan di Serial Monitor muncul tulisan status, artinya Arduino Uno kamu **100% SEHAT dan SIAP DIGUNAKAN!** 🎉
