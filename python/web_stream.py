"""
Live Camera Web Stream (CCTV Dashboard)
File: web_stream.py
Fungsi: Menyiarkan video kamera laptop langsung ke browser (Chrome/Edge)
Buka di browser: http://localhost:5000
"""

import cv2
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

class CamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>CCTV Monitoring - APD Checker</title>
                <style>
                    body { font-family: Arial, sans-serif; background: #121212; color: #fff; text-align: center; margin: 0; padding: 20px; }
                    .header { background: #1f1f1f; padding: 15px; border-radius: 8px; max-width: 800px; margin: 0 auto 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
                    h2 { margin: 0 0 10px; color: #4CAF50; }
                    .badge { display: inline-block; background: #2e7d32; color: white; padding: 4px 12px; border-radius: 12px; font-size: 14px; font-weight: bold; }
                    .video-box { max-width: 800px; margin: 0 auto; background: #000; border-radius: 8px; overflow: hidden; border: 2px solid #333; }
                    img { width: 100%; height: auto; display: block; }
                    .footer { margin-top: 15px; font-size: 13px; color: #888; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>🛡️ CCTV MONITORING - SISTEM PENGECEK APD</h2>
                    <div>Status Kamera: <span class="badge">LIVE ONLINE (CAP_DSHOW)</span></div>
                </div>
                <div class="video-box">
                    <img src="/stream.mjpg" />
                </div>
                <div class="footer">APD Checker - Proyek Sekolah AI & Arduino Uno</div>
            </body>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            while True:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                # Gambar overlay informasi di frame
                cv2.putText(frame, "CCTV LIVE - APD MONITORING", (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.putText(frame, time.strftime("%Y-%m-%d %H:%M:%S"), (20, frame.shape[0] - 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                _, jpeg = cv2.imencode('.jpg', frame)
                try:
                    self.wfile.write(b'--frame\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(jpeg)))
                    self.end_headers()
                    self.wfile.write(jpeg.tobytes())
                    self.wfile.write(b'\r\n')
                    time.sleep(0.03) # ~30 FPS
                except Exception:
                    break

def main():
    server = HTTPServer(('0.0.0.0', 5000), CamHandler)
    print("Server CCTV Live Stream aktif di: http://localhost:5000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    cap.release()

if __name__ == "__main__":
    main()
