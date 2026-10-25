"""Local PC debug ONLY. No ADB, serial, GPIO, inference, or board configuration.

Demo uses synthetic detections. Preview reads an explicitly supplied RTSP URL;
never mixes simulated PPE with real camera frames. Thermal acknowledgement is
an operator gate, NOT an automatic determination that the hardware is safe.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .config import ROOT
from .tracking import INDICATOR_COLORS, model_capabilities
from .tracking_offline import load_workshop_config, replay_tracking
from .config import load_config


MAX_LINE = 4096
BOARD_TTL = 3.5
CAMERA_TTL = 2.0


def demo_rows():
    """Synthetic same-person removal/re-wearing, all three items, then expiry."""
    rows = []
    boxes = {'vest': [20, 60, 80, 130], 'shoes': [10, 170, 90, 195],
             'helmet': [10, 5, 60, 35]}
    person = {'label': 'person', 'confidence': 0.95, 'box': [0, 0, 100, 200]}

    def add(scenario, removed=None, missing=None, person_visible=True):
        ppe = [dict(label=('no_' if kind == removed else '') + kind,
                    confidence=0.95, box=box)
               for kind, box in boxes.items() if kind != missing]
        rows.append(dict(frame_id=len(rows)+1, t=round(len(rows)*0.3, 3),
                         scenario=scenario, person=[person] if person_visible else [],
                         ppe=ppe if person_visible else [],
                         visibility={'0': {k: 'NOT_VISIBLE' if k == missing else 'OBSERVABLE'
                                           for k in boxes}} if person_visible else {}))

    for _ in range(3):
        add('APD lengkap: konfirmasi awal')
    for kind in boxes:
        for _ in range(7):
            add('Melepas ' + kind + ': bukti negatif sintetis', removed=kind)
        for _ in range(3):
            add('Memasang ulang ' + kind, removed=None)
    for _ in range(9):
        add('Kaki tertutup: cache lalu UNKNOWN, bukan pelanggaran', missing='shoes')
    for _ in range(3):
        add('Orang keluar frame', person_visible=False)
    return rows


def validate_heartbeat(row):
    """Only accept probe schema. This is debug telemetry, NOT authenticated safety IO."""
    if not isinstance(row, dict):
        raise ValueError('Heartbeat must be an object')
    if type(row.get('schema_version')) is not int or row['schema_version'] != 1:
        raise ValueError('Unsupported heartbeat schema')
    if row.get('kind') != 'BOARD_HEARTBEAT':
        raise ValueError('Unsupported signal kind')
    if (row.get('probe_only') is not True or row.get('ai_running') is not False or
            row.get('hardware_outputs_enabled') is not False):
        raise ValueError('Only outputs-disabled probe telemetry is accepted')
    if type(row.get('seq')) is not int or row['seq'] < 1:
        raise ValueError('Invalid heartbeat sequence')
    uptime = row.get('uptime_seconds')
    if (type(uptime) not in (int, float) or not math.isfinite(uptime) or uptime < 0):
        raise ValueError('Invalid uptime')
    raw = row.get('thermal_zone0_raw')
    if raw is not None and (type(raw) is not int or not -1000000 <= raw <= 1000000):
        raise ValueError('Invalid raw thermal value')
    name = row.get('thermal_zone0_type')
    if name is not None and (not isinstance(name, str) or len(name) > 120):
        raise ValueError('Invalid thermal type')
    return {key: row.get(key) for key in ('schema_version', 'kind', 'seq', 'uptime_seconds',
            'thermal_zone0_raw', 'thermal_zone0_type', 'probe_only', 'ai_running',
            'hardware_outputs_enabled')}


class DebugState:
    def __init__(self, mode, clock=time.monotonic):
        self.mode, self.clock = mode, clock
        self.lock = threading.Lock()
        self.report = None
        self.events = []
        self.demo_updated = None
        self.board = None
        self.board_seen = None
        self.board_error = None
        self.camera_jpeg = None
        self.camera_seen = None
        self.camera_status = 'STARTING' if mode == 'CAMERA_PREVIEW' else 'NOT_REQUESTED'
        self.cycle = 0
        self.capabilities = model_capabilities(load_config()['models']['ppe']['expected_labels'])

    def publish_demo(self, report, cycle):
        if self.mode != 'DEMO' or report.get('hardware_outputs_enabled') is not False:
            raise ValueError('Synthetic PPE can only be published in DEMO')
        with self.lock:
            if self.cycle != cycle:
                self.events.clear()
            self.cycle = cycle
            self.report = copy.deepcopy(report)
            self.demo_updated = self.clock()
            for person in report['people']:
                for kind, item in person['items'].items():
                    if item.get('transition'):
                        self.events.append(dict(frame_id=report['frame_id'], track_id=person['track_id'],
                                                item=kind, **item['transition']))
            self.events = self.events[-48:]

    def accept_heartbeat(self, row):
        row = validate_heartbeat(row)
        with self.lock:
            if self.board is not None and (row['seq'] <= self.board['seq'] or
                    row['uptime_seconds'] < self.board['uptime_seconds']):
                raise ValueError('Repeated/backwards heartbeat; restart PC session after reboot')
            self.board, self.board_seen, self.board_error = row, self.clock(), None

    def reject_heartbeat(self, reason):
        with self.lock:
            self.board_error = str(reason)[:180]

    def publish_camera(self, jpeg):
        if self.mode != 'CAMERA_PREVIEW':
            raise ValueError('Camera cannot be published into synthetic demo')
        with self.lock:
            self.camera_jpeg, self.camera_seen, self.camera_status = jpeg, self.clock(), 'FRAME_RECEIVED'

    def camera_fault(self, status):
        with self.lock:
            self.camera_jpeg, self.camera_status = None, status

    def jpeg(self):
        with self.lock:
            if self.camera_seen is None or self.clock()-self.camera_seen > CAMERA_TTL:
                return None
            return self.camera_jpeg

    def snapshot(self):
        with self.lock:
            now = self.clock()
            board_age = None if self.board_seen is None else max(0, now-self.board_seen)
            board_status = ('INVALID' if self.board_error else 'NOT_RECEIVED' if board_age is None else
                            'STALE' if board_age > BOARD_TTL else 'RECEIVED')
            cam_age = None if self.camera_seen is None else max(0, now-self.camera_seen)
            camera_status = self.camera_status
            if camera_status == 'FRAME_RECEIVED' and cam_age is not None and cam_age > CAMERA_TTL:
                camera_status = 'STALE'
            report = copy.deepcopy(self.report)
            demo_stale = (self.demo_updated is not None and now-self.demo_updated > CAMERA_TTL)
            if demo_stale:
                report = None
            return dict(schema_version=1, mode=self.mode, simulated=self.mode == 'DEMO',
                        demo_status=('NOT_REQUESTED' if self.mode != 'DEMO' else
                                     'STALE' if demo_stale else 'RUNNING' if report else 'STARTING'),
                        cycle=self.cycle, ai_running=False, ppe_inference_ready=False,
                        deployment_ready=False, arduino_connected_by_app=False,
                        hardware_outputs_enabled=False, model_capabilities=self.capabilities,
                        report=report, transitions=copy.deepcopy(self.events),
                        board=dict(status=board_status, received_age_seconds=board_age,
                                   telemetry=copy.deepcopy(self.board), error=self.board_error,
                                   thermal_safety_verified=False),
                        camera=dict(status=camera_status, received_age_seconds=cam_age,
                                    inference_enabled=False))


class TelemetryTail:
    """Read ONLY appended JSONL. Existing content is history and skipped at startup."""
    def __init__(self, path, state):
        self.path, self.state = Path(path), state
        stat = self.path.stat() if self.path.exists() else None
        self.offset = stat.st_size if stat else 0
        self.identity = (stat.st_dev, stat.st_ino) if stat else None
        self.blocked = False
        self.pending = b''
        self.discarding = False

    def poll(self):
        if self.blocked or not self.path.exists():
            return
        stat = self.path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if self.identity is not None and identity != self.identity:
            self.state.reject_heartbeat('Telemetry file replaced; restart PC debug session')
            self.blocked = True
            return
        self.identity = identity
        size = stat.st_size
        if size < self.offset:
            # Do not let a truncation/replay revive previous data as a fresh heartbeat.
            self.state.reject_heartbeat('Telemetry file truncated; restart PC debug session')
            self.offset, self.pending, self.discarding = size, b'', False
            self.blocked = True
            return
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            chunk = stream.read(65536)
            self.offset += len(chunk)
        if not chunk:
            return
        for fragment in chunk.splitlines(keepends=True):
            ended = fragment.endswith(b'\n')
            if not self.discarding:
                self.pending += fragment
                if len(self.pending) > MAX_LINE:
                    self.state.reject_heartbeat('Oversized telemetry line')
                    self.pending, self.discarding = b'', True
            if ended:
                if not self.discarding and self.pending.strip():
                    try:
                        self.state.accept_heartbeat(json.loads(self.pending.decode('utf-8-sig')))
                    except (ValueError, UnicodeError) as exc:
                        self.state.reject_heartbeat(exc)
                self.pending, self.discarding = b'', False


def run_preview(url, state, stop):
    # No board service start: only read a stream already made available by operator.
    cap = None
    try:
        import cv2
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1500])
        if not cap.isOpened():
            state.camera_fault('STREAM_UNAVAILABLE')
            return
        while not stop.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                state.camera_fault('CAMERA_LOST')
                return
            h, w = frame.shape[:2]
            if w > 800:
                frame = cv2.resize(frame, (800, max(1, int(h*800/w))))
            ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                state.camera_fault('ENCODE_ERROR')
                return
            state.publish_camera(encoded.tobytes())
            stop.wait(0.15)
    except Exception:
        # Do not echo RTSP credentials or backend exception details into the UI.
        state.camera_fault('PREVIEW_BACKEND_ERROR')
    finally:
        if cap is not None:
            cap.release()


def make_server(state, port=8765):
    page = Path(__file__).with_name('computer_debug.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlsplit(self.path).path not in ('/', '/api/status', '/camera.jpg'):
                self.send_error(404)
                return
            path = urlsplit(self.path).path
            if path == '/':
                body, content_type = page, 'text/html; charset=utf-8'
            elif path == '/api/status':
                body = json.dumps(state.snapshot(), allow_nan=False).encode('utf-8')
                content_type = 'application/json; charset=utf-8'
            else:
                body, content_type = state.jpeg(), 'image/jpeg'
                if body is None:
                    self.send_error(503, 'No fresh camera image')
                    return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--demo', action='store_true')
    modes.add_argument('--probe-only', action='store_true', help='Receive board heartbeat only, no camera')
    modes.add_argument('--rtsp', help='Verified, operator-provided existing stream; preview only')
    parser.add_argument('--thermal-checked', action='store_true', help='Operator acknowledgement, not temperature certification')
    parser.add_argument('--telemetry-file', type=Path, help='Tail newly appended probe JSONL; never starts ADB')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--duration', type=float, default=60, help='Bounded session, seconds (1..300)')
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or not 1 <= args.duration <= 300:
        parser.error('Duration must be 1..300 seconds')
    if not 1 <= args.port <= 65535:
        parser.error('Invalid port')
    if (args.rtsp or args.telemetry_file or args.probe_only) and not args.thermal_checked:
        parser.error('Live board/stream debug requires operator thermal acknowledgement')
    if args.probe_only and args.telemetry_file is None:
        parser.error('Probe-only needs --telemetry-file; application never starts board transport')
    if args.demo and args.telemetry_file:
        parser.error('Do not mix synthetic PPE demo with live board telemetry')
    if args.rtsp:
        try:
            parsed = urlsplit(args.rtsp)
            valid = parsed.scheme in ('rtsp', 'rtsps') and bool(parsed.hostname)
        except ValueError:
            valid = False
        if not valid:
            parser.error('Provide a verified RTSP URL; no host/address guessed by this application')
        try:
            import cv2  # noqa: F401 - host dependency preflight, no network/camera here
        except ImportError:
            parser.error('OpenCV is not installed in the host venv. Demo is available without it.')
    state = DebugState('DEMO' if args.demo else 'PROBE_ONLY' if args.probe_only else 'CAMERA_PREVIEW')
    reports = replay_tracking(demo_rows(), load_workshop_config()) if args.demo else []
    tail = TelemetryTail(args.telemetry_file, state) if args.telemetry_file else None
    stop = threading.Event()
    server = make_server(state, args.port)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    preview = None
    if args.rtsp:
        preview = threading.Thread(target=run_preview, args=(args.rtsp, state, stop), daemon=True)
        preview.start()
    print('PC-only debug: http://127.0.0.1:' + str(server.server_port), flush=True)
    print('MODE=' + state.mode + ' / AI=OFF / ARDUINO=OFF / HARDWARE_OUTPUTS=OFF', flush=True)
    print('Auto-stop after ' + str(args.duration) + ' seconds. Ctrl+C stops sooner.', flush=True)
    started, index = time.monotonic(), 0
    try:
        while time.monotonic()-started < args.duration:
            if reports:
                state.publish_demo(reports[index % len(reports)], index // len(reports)+1)
                index += 1
            if tail:
                try:
                    tail.poll()
                except OSError:
                    state.reject_heartbeat('Telemetry file unreadable')
            stop.wait(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        if preview:
            preview.join(timeout=6)
    return 0
