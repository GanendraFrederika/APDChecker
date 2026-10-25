"""Supervised HOST webcam/RTSP -> PPE1 receiver v2.2. Import has no I/O.

Default: local dashboard only, NO serial/actuation. Not a Luckfox RKNN backend.
Camera/inference run independently of browser clients. Unknown is not safe.
"""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
import time

from .config import ROOT, verify_model
from .detector import HostDetector, rotate_image
from .ppe_bridge import Decision, DecisionFilter, encode_status
from .rules import assess, normal_label

DEFAULT_CONFIG = ROOT / "config/apd_live.json"


def load_live_config(path=DEFAULT_CONFIG):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("schema_version") != 1 or config.get("stage") != "HOST_LIVE_SUPERVISED_PROTOTYPE":
        raise ValueError("Unsupported live configuration")
    if config.get("target", {}).get("deployment_enabled") is not False or config.get("actuators", {}).get("enabled") is not False:
        raise ValueError("Keep deployment_enabled=false and actuators.enabled=false; use supervised CLI gate")
    p = config["policy"]
    if len(p["required"]) != 3 or set(p["required"]) != {"helmet", "shoes", "vest"}:
        raise ValueError("Receiver map requires helmet, shoes and vest")
    if not math.isfinite(p["confidence"]) or not 0 < p["confidence"] <= 1:
        raise ValueError("Invalid confidence")
    if p["rotation_degrees"] not in (0, 90, 180, 270):
        raise ValueError("Invalid rotation")
    size = p["input_size"]
    if isinstance(size, bool) or not isinstance(size, int) or not 32 <= size <= 1280 or size % 32:
        raise ValueError("Invalid input size")
    age = p["max_frame_age_seconds"]
    if not math.isfinite(age) or not 0 < age <= 2:
        raise ValueError("Frame-age bound must be in (0, 2] seconds")
    make_filter(config)  # Validate before hardware access.
    return config


def make_filter(config):
    p = config["policy"]
    return DecisionFilter(p["violation_seconds"], p["clear_seconds"], p["min_samples"], p["max_gap_seconds"])


class LiveDetector:
    """Reuse person association; permit PARTIAL model capability but report UNKNOWN.

    No generic YOLO fallback, substring matching, or absence-of-box => no_*.
    """
    def __init__(self, config):
        self.config = config
        paths = {kind: verify_model(spec)[0] for kind, spec in config["models"].items()}
        os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".cache/ultralytics"))
        os.environ.setdefault("YOLO_AUTOINSTALL", "false")
        import torch
        torch.set_num_threads(2)
        from ultralytics import YOLO, settings
        settings.update({"sync": False, "hub": False})
        self.ppe = YOLO(str(paths["ppe"]))
        self.person = YOLO(str(paths["person"]))
        names = self.ppe.names
        labels = [normal_label(names[i]) for i in sorted(names)]
        if labels != config["models"]["ppe"]["expected_labels"]:
            raise ValueError("PPE label contract mismatch; no fallback")
        if not any(k in labels or "no_" + k in labels for k in config["policy"]["required"]):
            raise ValueError("Not a PPE model")
        self.unsupported_items = [k for k in config["policy"]["required"] if k not in labels or "no_" + k not in labels]
        self.person_ids = [i for i, name in self.person.names.items() if normal_label(name) == "person"]
        if len(self.person_ids) != 1:
            raise ValueError("Exactly one person class required")

    def infer(self, image):
        if image is None or image.size == 0:
            raise ValueError("Empty camera frame")
        p = self.config["policy"]
        args = dict(imgsz=p["input_size"], conf=p["confidence"], device="cpu", verbose=False, max_det=128)
        people = HostDetector._rows(self.person.predict(image, classes=self.person_ids, **args)[0])
        equipment = HostDetector._rows(self.ppe.predict(image, **args)[0])
        report = assess(people, equipment, p["required"], p["confidence"])
        report["detections"] = {"person": [asdict(d) for d in people], "ppe": [asdict(d) for d in equipment]}
        report["unsupported_items"] = self.unsupported_items
        if len(people) >= 128 or len(equipment) >= 128:
            report["observation"] = "MODEL_ERROR"
        if self.unsupported_items and report["observation"] == "COMPLIANT":
            report["observation"] = "UNKNOWN"
        return report


class StatusPublisher:
    """Called only for fresh decisions (or explicit F); no cached-safe heartbeat."""
    def __init__(self, stream, heartbeat=0.5):
        self.stream = stream
        self.heartbeat = heartbeat
        self.last = None
        self.sent_at = None

    def send(self, decision, now):
        if decision != self.last or self.sent_at is None or now - self.sent_at >= self.heartbeat:
            packet = encode_status(decision.state, decision.mask)
            written = self.stream.write(packet)
            if written != len(packet):
                raise OSError("Incomplete serial write")
            self.last, self.sent_at = decision, now
            return True
        return False


def open_receiver(port, serial_factory=None, clock=time.monotonic, sleep=time.sleep):
    if serial_factory is None:
        import serial
        serial_factory = serial.Serial
    stream = serial_factory(port, 9600, timeout=0.1, write_timeout=0.25)
    deadline = clock() + 6.0
    # Opening USB may reset Uno. Never assume an old legacy/APD3 receiver is PPE1.
    try:
        while clock() < deadline:
            line = stream.readline()
            if line.startswith(b"READY - APD Receiver v2.2 [PPE1 "):
                return stream
            sleep(0.01)
        raise RuntimeError("No PPE1/v2.2 READY; refusing to send to old firmware/APD3. Check COM port and reset Uno.")
    except BaseException:
        stream.close()
        raise


class FreshDecisionEngine:
    """Supervise inference freshness independently of web clients and transport."""
    def __init__(self, config):
        self.config = config
        self.filter = make_filter(config)
        self.previous_generation = -1
        self.decision = Decision("F")

    def update(self, snapshot, now):
        generation, captured, report, _, _ = snapshot
        age = now - captured
        fresh = bool(captured) and 0 <= age <= self.config["policy"]["max_frame_age_seconds"]
        if not fresh:
            if self.decision.state != "F":
                self.filter = make_filter(self.config)
            self.decision = Decision("F")
        elif generation != self.previous_generation:
            self.decision = self.filter.update(report, captured)
        self.previous_generation = generation
        return self.decision


class CameraUnavailable(RuntimeError):
    pass


class SharedCamera:
    def __init__(self):
        self.lock = threading.Lock()
        self.report = {"observation": "STARTING", "people": []}
        self.captured_at = 0.0
        self.generation = 0
        self.jpeg = None
        self.error = ""

    def publish(self, report, captured_at, jpeg=None, error=""):
        with self.lock:
            self.report, self.captured_at, self.jpeg, self.error = report, captured_at, jpeg, error
            self.generation += 1

    def snapshot(self):
        with self.lock:
            return self.generation, self.captured_at, self.report, self.jpeg, self.error


def camera_source(value):
    return int(value) if value.isdecimal() else value


def camera_worker(shared, stop, config, source, show_window=False):
    cap = None
    try:
        import cv2
        detector = LiveDetector(config)
        source = camera_source(source)
        if isinstance(source, str):
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000])
        else:
            cap = cv2.VideoCapture(source, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        if not cap.isOpened():
            raise CameraUnavailable("Camera failed to open")
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        while not stop.is_set():
            captured_at = time.monotonic()  # Conservative read+inference age, NOT sensor timestamp.
            ok, frame = cap.read()
            if not ok:
                raise CameraUnavailable("Camera frame lost")
            frame = rotate_image(frame, config["policy"]["rotation_degrees"])
            report = detector.infer(frame)
            if time.monotonic() - captured_at > config["policy"]["max_frame_age_seconds"]:
                report["observation"] = "CAMERA_LOST"
            # Visible boxes: never call an individual helmet box APD LENGKAP.
            for person in report["people"]:
                x1, y1, x2, y2 = map(int, person["box"])
                color = {"VIOLATION": (0, 0, 255), "COMPLIANT": (0, 200, 0)}.get(person["state"], (0, 220, 255))
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = person["state"] + " missing:" + ",".join(person["explicit_missing"])
                cv2.putText(frame, label, (x1, max(25, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1)
            banner = "HOST PROTOTYPE / " + report["observation"]
            if detector.unsupported_items:
                banner += " / UNSUPPORTED:" + ",".join(detector.unsupported_items)
            cv2.putText(frame, banner, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 220, 255), 1)
            if show_window:
                cv2.imshow("APD - supervised HOST prototype", frame)
                if cv2.waitKey(1) & 0xff == ord("q"):
                    stop.set()
            encoded, jpeg = cv2.imencode(".jpg", frame)
            shared.publish(report, captured_at, jpeg.tobytes() if encoded else None)
    except Exception as exc:
        shared.publish({"observation": "CAMERA_LOST" if isinstance(exc, CameraUnavailable) else "MODEL_ERROR", "people": []}, time.monotonic(), error=str(exc))
    finally:
        if cap is not None:
            cap.release()
        if show_window:
            try:
                import cv2
                cv2.destroyAllWindows()
            except Exception:
                pass


HTML = """<!doctype html><html lang="id"><meta charset="utf-8"><title>APD Camera - HOST</title>
<style>body{font:16px system-ui;background:#101827;color:#e2e8f0;max-width:1000px;margin:30px auto;padding:16px}img{width:100%;border-radius:12px}pre{white-space:pre-wrap;background:#1e293b;padding:20px;border-radius:12px}strong{color:#fbbf24}</style>
<h1>CCTV APD — prototipe HOST</h1><p><strong>Merah: helm · Kuning: sepatu · Hijau: rompi</strong></p>
<p>UNKNOWN bukan APD lengkap. Model saat ini belum mendukung rompi. Serial OFF kecuali diaktifkan eksplisit saat peluncuran.</p>
<img src="/stream.mjpg" alt="Kamera"><pre id="status">Menunggu status...</pre>
<script>setInterval(async()=>{try{let s=await(await fetch('/api/status')).json();document.getElementById('status').textContent=JSON.stringify(s,null,2)}catch(e){document.getElementById('status').textContent='Koneksi dashboard terputus'}},500)</script></html>"""


def handler_for(shared, runtime, max_age):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                data, kind = HTML.encode(), "text/html; charset=utf-8"
            elif self.path == "/api/status":
                generation, captured, report, _, error = shared.snapshot()
                fresh = bool(captured) and 0 <= time.monotonic() - captured <= max_age
                body = dict(report=report, fresh=fresh, error=error, runtime=dict(runtime), generation=generation)
                data, kind = json.dumps(body, allow_nan=False).encode(), "application/json"
            elif self.path == "/stream.mjpg":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                last = -1
                try:
                    while not runtime["stopped"]:
                        generation, _, _, jpeg, _ = shared.snapshot()
                        if jpeg and generation != last:
                            last = generation
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                             + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Browser closed; camera keeps running independently.
                return
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return Handler


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", default="0", help="Webcam index or existing RTSP URL (does not start Luckfox)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--port", help="Explicit Arduino COM port; never auto-select a device")
    parser.add_argument("--enable-serial", action="store_true", help="SUPERVISED TEST: permits actual relay/audio/servo commands")
    parser.add_argument("--confirm-legacy-v22", action="store_true", help="Confirm v2.2/PPE1 receiver and safe actuator area; not APD3")
    parser.add_argument("--http-port", type=int, default=5000)
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--show", action="store_true", help="Open local camera window; q stops")
    parser.add_argument("--duration", type=float, default=300, help="Bounded supervised run, 1..600 seconds")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # Serial needs all three explicit gates; any partial combination is rejected before I/O.
    if args.enable_serial and not (args.port and args.confirm_legacy_v22):
        parser.error("Serial requires --port COMx --enable-serial --confirm-legacy-v22")
    if not args.enable_serial and (args.port or args.confirm_legacy_v22):
        parser.error("Do not pass serial options without --enable-serial")
    if not math.isfinite(args.duration) or not 1 <= args.duration <= 600 or not 1024 <= args.http_port <= 65535:
        parser.error("Duration 1..600 seconds / HTTP port 1024..65535")
    config = load_live_config(args.config)
    shared, stop = SharedCamera(), threading.Event()
    runtime = dict(serial_enabled=False, decision="F", mask=0, stopped=False)
    stream = publisher = server = worker = None
    engine = FreshDecisionEngine(config)
    result = 0
    try:
        if not args.no_web:
            server = ThreadingHTTPServer(("127.0.0.1", args.http_port),
                                         handler_for(shared, runtime, config["policy"]["max_frame_age_seconds"]))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print("Dashboard: http://127.0.0.1:" + str(args.http_port) + " (read-only)", flush=True)
        if args.enable_serial:
            stream = open_receiver(args.port)
            publisher = StatusPublisher(stream)
            publisher.send(Decision("F"), time.monotonic())
            runtime["serial_enabled"] = True
            print("SUPERVISED SERIAL ENABLED: real actuators may operate", flush=True)
        else:
            print("SERIAL OFF: camera/dashboard only; no Arduino port opened", flush=True)
        worker = threading.Thread(target=camera_worker, args=(shared, stop, config, args.camera, args.show), daemon=True)
        worker.start()
        deadline = time.monotonic() + args.duration
        previous_logged = None
        while not stop.is_set() and time.monotonic() < deadline:
            snapshot = shared.snapshot()
            error = snapshot[4]
            now = time.monotonic()
            decision = engine.update(snapshot, now)
            runtime.update(decision=decision.state, mask=decision.mask)
            if publisher:
                publisher.send(decision, now)
                # Drain receiver diagnostics to avoid an unread serial TX backlog.
                waiting = getattr(stream, "in_waiting", 0)
                if waiting:
                    stream.read(min(waiting, 512))
            logged = (decision, error)
            if logged != previous_logged:
                print(json.dumps({"state": decision.state, "mask": decision.mask, "error": error}), flush=True)
                previous_logged = logged
            if error:
                result = 2
                break
            stop.wait(.05)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print("STOP:", exc, flush=True)
        result = 2
    finally:
        stop.set()
        runtime["stopped"] = True
        if publisher:
            try:
                # Explicit monitor fault, not a false COMPLIANT/NO_PERSON or legacy '0'.
                publisher.send(Decision("F"), time.monotonic())
            except Exception:
                pass  # MCU's 3-second timeout is the fallback on broken transport.
        if stream:
            stream.close()
        if server:
            server.shutdown()
            server.server_close()
        if worker:
            worker.join(timeout=2)
    return result
