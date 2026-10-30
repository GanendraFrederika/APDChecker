"""Camera preview for straightening the camera (no AI models: light on memory).

Shows the Luckfox picture with only the 90-degree rotation (the software tilt
correction is OFF by default, so the real tilt of the tube is visible), a guide grid
and a live spirit level estimated from straight lines in the scene. The window opens
centred on the screen, sized to the picture. "Simpan" writes the rotation (and the
tilt correction shown) to config/sentinel.json.

  preview-camera.bat
  .venv\\Scripts\\python.exe scripts\\preview_camera.py [--source 0|rtsp://..|foto.jpg] [--no-window]
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
CONFIG = ROOT / "config/sentinel.json"
PAGE = Path(__file__).with_name("preview_camera.html")
SENSOR = (2304, 1296)                 # SC3336 stream (landscape)
PANEL_W, MARGIN = 300, 20             # must match the CSS in preview_camera.html


# ---------------------------------------------------------------- spirit level
def level_estimate(frame):
    """Tilt of the picture from its straight lines (door frames, walls, shelves).

    Every line votes for its deviation from the nearest axis, weighted by length; the
    strongest 1-degree peak wins. Vertical lines (door frames, wall corners) are used
    on their own when there are enough of them: horizontal lines (floor tiles, shelf
    edges) converge in perspective and would fake a tilt. Positive = picture turned
    clockwise (the right side is lower). Returns None when there are too few lines."""
    import cv2
    import numpy as np
    h, w = frame.shape[:2]
    s = 480.0 / max(h, w)
    g = cv2.cvtColor(cv2.resize(frame, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA),
                     cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=40,
                            minLineLength=int(0.12 * max(g.shape)), maxLineGap=5)
    if lines is None or len(lines) < 3:
        return None
    seg = lines[:, 0, :].astype(float)
    dx, dy = seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]
    ang = np.degrees(np.arctan2(dy, dx))
    dev = (ang + 45.0) % 90.0 - 45.0
    length = np.hypot(dx, dy)
    fold = ang % 180.0
    vert = (fold >= 45.0) & (fold < 135.0)
    family = "tegak"
    if vert.sum() >= 3 and length[vert].sum() >= 0.3 * length.sum():
        dev, length = dev[vert], length[vert]
    else:
        family = "semua"
    hist = np.bincount(((dev + 45.0) // 1).astype(int) % 90, weights=length, minlength=90)
    smooth = hist + np.roll(hist, 1) + np.roll(hist, -1)
    peak = int(np.argmax(smooth)) - 45 + 0.5
    rel = (dev - peak + 45.0) % 90.0 - 45.0
    near = np.abs(rel) <= 2.0
    if near.sum() < 3:
        return None
    angle = (peak + float(np.average(rel[near], weights=length[near])) + 45.0) % 90.0 - 45.0
    share = float(length[near].sum() / length.sum())
    return dict(angle=round(angle, 1), share=round(share, 2), lines=int(near.sum()), family=family,
                sure=bool(share >= 0.25 and near.sum() >= 4))


# ---------------------------------------------------------------- state
class Preview:
    def __init__(self, source, use_luckfox):
        from sentinel.camera import LatestFrame
        cfg = self.load_config()
        cam = cfg.get("camera", {})
        self.rotate = int(cam.get("rotate", 0)) % 360
        self.roll_cfg = float(cam.get("roll_deg", 0.0))
        self.roll_on = False                   # show the REAL tilt by default
        self.camera = LatestFrame(source, rotate=self.rotate, roll=0.0).start()
        self.fox = None
        self.pico = "-"
        if use_luckfox:
            from sentinel.luckfox import Luckfox
            self.fox = Luckfox()
            self.pico = "Mencari Pico..."
        self.lock = threading.Lock()
        self.jpeg, self.jseq, self.view = None, 0, None
        self.frame, self.frame_at = None, 0.0
        self.level = None
        self.saved_msg = ""
        self.stop = threading.Event()

    @staticmethod
    def load_config():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def apply(self):
        self.camera.set_rotate(self.rotate, self.roll_cfg if self.roll_on else 0.0)

    def save(self):
        cfg = self.load_config()
        cam = cfg.setdefault("camera", {})
        roll = round(self.roll_cfg, 1) if self.roll_on else 0.0
        cam["rotate"], cam["roll_deg"] = self.rotate, roll
        CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.roll_cfg = roll
        self.saved_msg = (f"Tersimpan {time.strftime('%H:%M:%S')}: putaran {self.rotate}°, "
                          f"koreksi miring {roll:+.1f}°")
        return self.saved_msg

    def status(self):
        now = time.monotonic()
        with self.lock:
            view, frame_at, level = self.view, self.frame_at, self.level
        fresh = frame_at and now - frame_at < 3.0
        portrait = self.rotate in (90, 270)
        default_view = (SENSOR[1], SENSOR[0]) if portrait else SENSOR
        return dict(pico=self.pico, luckfox=self.fox is not None, frame_ok=bool(fresh),
                    fps=round(self.camera.fps, 1), error=self.camera.error,
                    view=list(view or default_view), rotate=self.rotate,
                    roll_on=self.roll_on, roll_cfg=self.roll_cfg,
                    level=level if fresh else None, saved=self.saved_msg)

    # ------------------------------------------------------------ threads
    def encoder(self):
        """Newest frame -> JPEG for the browser (long side <= 1280 px)."""
        import cv2
        last = -1
        while not self.stop.is_set():
            seq, _, frame = self.camera.read()
            if frame is None or seq == last:
                time.sleep(0.03)
                continue
            last = seq
            h, w = frame.shape[:2]
            s = min(1.0, 1280.0 / max(h, w))
            small = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else frame
            ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                with self.lock:
                    self.jpeg, self.jseq = jpg.tobytes(), self.jseq + 1
                    self.view, self.frame, self.frame_at = (w, h), frame, time.monotonic()

    def leveler(self):
        while not self.stop.wait(0.8):
            with self.lock:
                frame = self.frame
            if frame is not None:
                try:
                    est = level_estimate(frame)
                except Exception:
                    est = None
                with self.lock:
                    self.level = est

    def luckfox_watchdog(self):
        """Same healing as the main app: forward after a replug, renew the 300 s
        on-board camera guard, re-apply the light profile."""
        while not self.stop.is_set():
            try:
                if not self.fox.present():
                    self.pico = "Menunggu Pico (USB)"
                else:
                    self.fox.ensure_forward()
                    if not self.fox.camera_running():
                        self.pico = "Menyalakan kamera..."
                        self.fox.ensure_profile()
                        self.fox.start_camera()
                    self.pico = "Terhubung"
            except Exception as exc:
                self.pico = "ADB: " + str(exc)[:40]
            self.stop.wait(5)


# ---------------------------------------------------------------- web
def make_handler(pv):
    page = PAGE.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, kind, data):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj):
            return self._send(200, "application/json", json.dumps(obj).encode())

        def do_GET(self):
            if self.path == "/":
                return self._send(200, "text/html; charset=utf-8", page)
            if self.path == "/api/status":
                return self._json(pv.status())
            if self.path.startswith("/stream.mjpg"):
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                last = -1
                try:
                    while not pv.stop.is_set():
                        with pv.lock:
                            jpeg, seq = pv.jpeg, pv.jseq
                        if jpeg and seq != last:
                            last = seq
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                             + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                        time.sleep(0.03)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                return
            return self._send(404, "text/plain", b"not found")

        def do_POST(self):
            length = min(int(self.headers.get("Content-Length") or 0), 1024)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, "text/plain", b"bad json")
            if self.path == "/api/rotate":
                pv.rotate = (pv.rotate + (90 if body.get("dir", 1) > 0 else -90)) % 360
                pv.apply()
            elif self.path == "/api/roll":
                pv.roll_on = bool(body.get("on")) and abs(pv.roll_cfg) >= 0.1
                pv.apply()
            elif self.path == "/api/save":
                pv.save()
            else:
                return self._send(404, "text/plain", b"not found")
            return self._json(pv.status())

    return Handler


# ---------------------------------------------------------------- window
def work_area():
    """Usable screen area (without the taskbar) in logical pixels."""
    try:
        from ctypes import wintypes
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)   # SPI_GETWORKAREA
        scale = 1.0
        try:
            scale = ctypes.windll.user32.GetDpiForSystem() / 96.0
        except Exception:
            pass
        return (rect.left / scale, rect.top / scale, (rect.right - rect.left) / scale,
                (rect.bottom - rect.top) / scale)
    except Exception:
        return 0, 0, 1366, 728


def window_geometry(aspect):
    """Window centred on the screen, picture as tall as fits, panel on the right.
    Same formula as fitWindow() in the page (which refines it once the page runs)."""
    left, top, aw, ah = work_area()
    title_h, border_w = 32, 16
    inner_h = round(ah * 0.86) - title_h
    fh = inner_h - 2 * MARGIN
    fw = fh * aspect
    inner_w = fw + PANEL_W + 3 * MARGIN
    max_w = round(aw * 0.92) - border_w
    if inner_w > max_w:
        inner_w = max_w
        fh = (inner_w - PANEL_W - 3 * MARGIN) / aspect
        inner_h = max(fh + 2 * MARGIN, 560)
    w, h = round(inner_w + border_w), round(inner_h + title_h)
    return w, h, round(left + (aw - w) / 2), round(top + (ah - h) / 2)


def find_browser():
    env = os.path.expandvars
    for p in (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
              r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
              r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
              r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
              r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(env(p)):
            return env(p)
    return None


def open_window(url, aspect):
    """App-style window (no tabs/address bar) in its own small browser profile.
    Returns the browser process, or None when the default browser was used."""
    browser = find_browser()
    if browser is None:
        import webbrowser
        webbrowser.open(url)
        return None
    w, h, x, y = window_geometry(aspect)
    profile = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "APDSentinel" / "preview-browser"
    return subprocess.Popen([browser, f"--app={url}", f"--window-size={w},{h}", f"--window-position={x},{y}",
                             f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                             "--disable-features=Translate"])


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="luckfox", help="'luckfox' (default), webcam index, RTSP URL or a photo")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--no-window", action="store_true", help="server only, do not open a window")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    use_fox = args.source == "luckfox"
    if use_fox:
        from sentinel.luckfox import RTSP_URL
        source = RTSP_URL
    else:
        source = args.source
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), None)
    except OSError:
        print(f"Preview sudah berjalan di {url} - membuka jendelanya saja.")
        if not args.no_window:
            open_window(url, 9 / 16)
        return 0
    pv = Preview(source, use_fox)
    server.RequestHandlerClass = make_handler(pv)
    server.daemon_threads = True
    threads = [pv.encoder, pv.leveler] + ([pv.luckfox_watchdog] if use_fox else [])
    for fn in threads:
        threading.Thread(target=fn, daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Preview kamera: {url}")
    print("Tutup jendela preview (atau tekan Ctrl+C di sini) untuk berhenti.")
    proc = None
    if not args.no_window:
        aspect = (SENSOR[1] / SENSOR[0]) if pv.rotate in (90, 270) else (SENSOR[0] / SENSOR[1])
        proc = open_window(url, aspect)
    started = time.monotonic()
    try:
        while not pv.stop.is_set():
            if proc is not None and proc.poll() is not None:
                if time.monotonic() - started > 4:
                    break                       # the preview window was closed
                proc = None                     # handed to an already running browser
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        pv.stop.set()
        pv.camera.stop()
        server.shutdown()
    print("Preview berhenti. (Kamera Pico mati sendiri dalam <= 5 menit.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
