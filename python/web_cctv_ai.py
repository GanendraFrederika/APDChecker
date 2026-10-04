"""
Sistem Deteksi APD Terpadu (AI Computer Vision + Web CCTV Dashboard + Arduino Uno)
File: web_cctv_ai.py
Buka di browser: http://localhost:5000
"""

import sys
import os
import cv2
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse

# Setup Serial Arduino
HAS_SERIAL = False
arduino = None
PORT_ARDUINO = "COM3"

try:
    import serial
    try:
        arduino = serial.Serial(PORT_ARDUINO, 9600, timeout=1)
        time.sleep(2)
        HAS_SERIAL = True
        print(f"[OK] Sukses terhubung ke Arduino Uno di {PORT_ARDUINO}")
    except Exception as e:
        print(f"[INFO] Arduino tidak tersambung ({e}). Berjalan dalam mode simulasi.")
except ImportError:
    print("[INFO] pyserial belum terpasang.")

def kirim_perintah_arduino(cmd_char):
    global arduino
    if arduino and arduino.is_open:
        try:
            arduino.write(cmd_char.encode())
            print(f"[ARDUINO] Mengirim sinyal: {cmd_char}")
        except Exception as e:
            print(f"[ERROR ARDUINO] {e}")

# Variabel State Global
status_sistem = {
    "alarm_aktif": False,
    "pesan": "PATROLI CCTV AKTIF (STANDBY 90°)",
    "jumlah_orang": 0,
    "jumlah_pelanggar": 0,
    "apd_status": "AMAN",
    "servo_status": "STANDBY 90°"
}

# Kamera Stream
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# Muat Model YOLO khusus APD
yolo_model = None
model_path = r"c:\Users\ASUS\Desktop\APDChecker\models\ppe_yolov8n.pt"

try:
    from ultralytics import YOLO
    if os.path.exists(model_path):
        print(f"[AI] Memuat model AI khusus APD: {model_path}...")
        yolo_model = YOLO(model_path)
        print("[AI] Model APD (Helmet/Mask/Goggles) siap digunakan!")
    else:
        print("[AI] Memuat model standar YOLOv8n...")
        yolo_model = YOLO("yolov8n.pt")
except Exception as e:
    print(f"[AI ERROR] Gagal memuat YOLO: {e}")

class CCTVHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Kontrol API lewat Web
        if path == '/api/alarm_on':
            status_sistem["alarm_aktif"] = True
            kirim_perintah_arduino('1')
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            return
        elif path == '/api/alarm_off':
            status_sistem["alarm_aktif"] = False
            kirim_perintah_arduino('0')
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            return
        elif path == '/api/patrol_now':
            # Paksa patroli 0 - 130 derajat sekarang
            kirim_perintah_arduino('T')
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            return
        elif path == '/api/status':
            import json
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(status_sistem).encode('utf-8'))
            return

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html lang="id">
            <head>
                <meta charset="UTF-8">
                <title>CCTV Smart APD Patrol & Monitoring</title>
                <style>
                    body { font-family: 'Segoe UI', Arial, sans-serif; background: #0b0f19; color: #e1e7ef; margin: 0; padding: 20px; }
                    .container { max-width: 1100px; margin: 0 auto; }
                    .header { background: #131b2e; padding: 18px 24px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center; border: 1px solid #1f2d4a; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
                    h1 { margin: 0; font-size: 20px; color: #38bdf8; display: flex; align-items: center; gap: 10px; }
                    .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
                    .video-panel { background: #131b2e; padding: 15px; border-radius: 12px; border: 1px solid #1f2d4a; }
                    .video-wrapper { position: relative; width: 100%; border-radius: 8px; overflow: hidden; background: #000; border: 2px solid #334155; }
                    .video-wrapper img { width: 100%; height: auto; display: block; }
                    .control-panel { background: #131b2e; padding: 20px; border-radius: 12px; border: 1px solid #1f2d4a; display: flex; flex-direction: column; gap: 15px; }
                    .card { background: #1a243b; padding: 15px; border-radius: 8px; border: 1px solid #2d3b59; }
                    .card-title { font-size: 12px; text-transform: uppercase; color: #94a3b8; margin-bottom: 8px; font-weight: bold; letter-spacing: 0.5px; }
                    .status-val { font-size: 20px; font-weight: bold; }
                    .status-aman { color: #4ade80; }
                    .status-bahaya { color: #f87171; }
                    .btn-group { display: flex; gap: 10px; flex-wrap: wrap; }
                    button { padding: 10px 16px; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; transition: 0.2s; font-size: 13px; }
                    .btn-blue { background: #0284c7; color: white; }
                    .btn-blue:hover { background: #0369a1; }
                    .btn-red { background: #dc2626; color: white; }
                    .btn-red:hover { background: #b91c1c; }
                    .btn-green { background: #16a34a; color: white; }
                    .btn-green:hover { background: #15803d; }
                    .badge-live { background: #ef4444; color: white; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; animation: pulse 1.5s infinite; }
                    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
                    .rule-list { font-size: 12px; line-height: 1.6; color: #cbd5e1; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🛡️ CCTV SMART APD PATROL <span class="badge-live">● PATROL MODE</span></h1>
                        <div style="font-size: 13px; color: #94a3b8;">Arduino Uno (COM3) • TOA Horn • Servo SG90</div>
                    </div>
                    
                    <div class="grid">
                        <div class="video-panel">
                            <div class="video-wrapper">
                                <img src="/stream.mjpg" alt="Live CCTV Stream">
                            </div>
                        </div>

                        <div class="control-panel">
                            <div class="card">
                                <div class="card-title">Status Deteksi APD AI</div>
                                <div id="statusBadge" class="status-val status-aman">AMAN (STANDBY 90°)</div>
                            </div>

                            <div class="card">
                                <div class="card-title">Kontrol Patroli Servo SG90</div>
                                <div class="btn-group">
                                    <button class="btn-blue" onclick="fetch('/api/patrol_now')">🔄 Mulai Patroli Sekarang (0°-130°)</button>
                                </div>
                                <div style="font-size: 11px; color: #94a3b8; margin-top: 8px;">
                                    * Otomatis memindai setiap 1 menit jika tidak ada orang.
                                </div>
                            </div>

                            <div class="card">
                                <div class="card-title">Uji Manual Alarm & LED</div>
                                <div class="btn-group">
                                    <button class="btn-red" onclick="fetch('/api/alarm_on')">🔊 Kunci & Bunyikan Alarm</button>
                                    <button class="btn-green" onclick="fetch('/api/alarm_off')">🔇 Stop Alarm & Balik ke 90°</button>
                                </div>
                            </div>

                            <div class="card">
                                <div class="card-title">Logika Kerja Cerdas</div>
                                <div class="rule-list">
                                    1. <strong>Normal:</strong> Kamera diam di 90°.<br>
                                    2. <strong>Tiap 1 Menit:</strong> Kamera patroli muter 0° - 130° mencari orang.<br>
                                    3. <strong>Orang Tanpa APD:</strong> Kamera <u>LANGSUNG BERHENTI</u> di sudut itu, alarm TOA berbunyi & LED kedip sinkron.<br>
                                    4. <strong>Saat APD Dipakai / Orang Pergi:</strong> Alarm mati, kamera kembali ke 90°, timer 1 menit di-reset!
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))

        elif path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()

            last_alarm_sent = False
            consecutive_violation = 0
            consecutive_clear = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                pelanggaran = False
                ada_orang = False
                ada_apd = False

                if yolo_model:
                    # Jalankan inferensi YOLO
                    results = yolo_model(frame, conf=0.35, verbose=False)
                    boxes = results[0].boxes

                    for box in boxes:
                        cls_id = int(box.cls[0])
                        label = yolo_model.names[cls_id].lower()
                        conf = float(box.conf[0])
                        x1, y1, x2, y2 = map(int, box.xyxy[0])

                        # Cek label deteksi
                        if "no_helmet" in label or "no_mask" in label:
                            ada_orang = True
                            pelanggaran = True
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            cv2.putText(frame, f"PELANGGARAN APD ({conf*100:.0f}%)", (x1, max(20, y1 - 10)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                        elif "helmet" in label or "mask" in label:
                            ada_orang = True
                            ada_apd = True
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(frame, f"APD LENGKAP ({conf*100:.0f}%)", (x1, max(20, y1 - 10)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                        elif "person" in label:
                            ada_orang = True
                            # Jika hanya orang tapi belum terdeteksi helm, kita tandai
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                            cv2.putText(frame, f"Orang Terdeteksi ({conf*100:.0f}%)", (x1, max(20, y1 - 10)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

                # Logika Debounce untuk Stabilitas
                if pelanggaran:
                    consecutive_violation += 1
                    consecutive_clear = 0
                else:
                    consecutive_clear += 1
                    consecutive_violation = 0

                # Picu Alarm & Lock jika ada pelanggaran selama 2 frame berturut-turut
                if consecutive_violation >= 2:
                    if not last_alarm_sent:
                        kirim_perintah_arduino('1') # Kunci servo di sudut saat ini & bunyikan alarm
                        last_alarm_sent = True
                        status_sistem["alarm_aktif"] = True
                        status_sistem["apd_status"] = "PELANGGARAN"
                
                # Matikan Alarm & Kembali ke 90° jika APD sudah dipakai atau orang pergi
                elif consecutive_clear >= 3:
                    if last_alarm_sent:
                        kirim_perintah_arduino('0') # Matikan alarm, balik ke 90 derajat, reset timer 1 menit
                        last_alarm_sent = False
                        status_sistem["alarm_aktif"] = False
                        status_sistem["apd_status"] = "AMAN"

                # Overlay Banner Status CCTV
                cv2.rectangle(frame, (0, 0), (frame.shape[1], 45), (15, 23, 42), -1)
                if status_sistem["alarm_aktif"]:
                    cv2.putText(frame, "⚠️ TARGET TERKUNCI: PELANGGARAN APD!", (15, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
                else:
                    cv2.putText(frame, "CCTV PATROL STANDBY - SEMUA AMAN", (15, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)

                cv2.putText(frame, time.strftime("%H:%M:%S"), (frame.shape[1] - 110, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

                _, jpeg = cv2.imencode('.jpg', frame)
                try:
                    self.wfile.write(b'--frame\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(jpeg)))
                    self.end_headers()
                    self.wfile.write(jpeg.tobytes())
                    self.wfile.write(b'\r\n')
                    time.sleep(0.03)
                except Exception:
                    break

def main():
    server = HTTPServer(('0.0.0.0', 5000), CCTVHandler)
    print("\n========================================================")
    print("Sistem CCTV Smart APD Patrol aktif di: http://localhost:5000")
    print("========================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    if cap.isOpened():
        cap.release()
    if arduino and arduino.is_open:
        arduino.write(b'0')
        arduino.close()

if __name__ == "__main__":
    main()
