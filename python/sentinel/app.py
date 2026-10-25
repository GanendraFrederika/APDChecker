"""APD Sentinel runtime: camera -> AI -> tracker -> brain -> Arduino, plus a live
web dashboard at http://127.0.0.1:8080 (loopback only).

Run:  .venv\\Scripts\\python.exe -m sentinel.app --camera luckfox --port COM6
      --camera 0            laptop webcam (no servo motion meaning, for AI tests)
      --port none           AI + dashboard only, Arduino not used
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time

from . import VERSION
from .brain import Brain, BrainConfig
from .camera import LatestFrame
from .geometry import CameraModel
from .luckfox import RTSP_URL, Luckfox
from .protocol import DEFAULT_LIMITS
from .tracker import ITEMS, Tracker
from .types import Command

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_WIDTH = 1152
COLORS = {"PRESENT": (60, 200, 60), "ABSENT": (40, 40, 235), "UNKNOWN": (0, 200, 255)}
STATE_COLORS = {"COMPLIANT": (60, 200, 60), "VIOLATION": (40, 40, 235), "CHECKING": (0, 200, 255)}
NAMES = {"helmet": "Helm", "vest": "Rompi", "shoes": "Sepatu", "glove": "Sarung"}


class Shared:
    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None
        self.status = {}
        self.jpeg_seq = 0

    def publish(self, jpeg, status):
        with self.lock:
            self.jpeg, self.status = jpeg, status
            self.jpeg_seq += 1


# ---------------------------------------------------------------- drawing
def draw(frame, tracks, decision, link_snap, fps, geom_info, lock_id):
    import cv2
    h, w = frame.shape[:2]
    for t in tracks:
        x1, y1, x2, y2 = map(int, t.pixel_box)
        state = t.state()
        color = STATE_COLORS[state]
        thick = 4 if t.tid == lock_id else 2
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick)
        if t.tid == lock_id:                                   # lock-on corner brackets
            L = max(12, (x2 - x1) // 5)
            for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
                cv2.line(frame, (cx, cy), (cx + dx * L, cy), (255, 255, 255), 2)
                cv2.line(frame, (cx, cy), (cx, cy + dy * L), (255, 255, 255), 2)
        for item in ITEMS:
            reg = t.regions.get(item)
            if reg is not None and reg.box is not None:
                rx1, ry1, rx2, ry2 = map(int, reg.box)
                cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), COLORS[t.items[item].state], 1)
        label = f"#{t.tid} {state}"
        cv2.rectangle(frame, (x1, max(0, y1 - 44)), (x1 + 210, y1), color, -1)
        cv2.putText(frame, label, (x1 + 4, max(14, y1 - 26)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        parts = " ".join(f"{NAMES[i][0]}:{ {'PRESENT':'OK','ABSENT':'X','UNKNOWN':'?'}[t.items[i].state] }"
                         for i in ITEMS)
        cv2.putText(frame, parts, (x1 + 4, max(28, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cx, cy = w // 2, h // 2
    cv2.line(frame, (cx - 14, cy), (cx + 14, cy), (255, 255, 255), 1)
    cv2.line(frame, (cx, cy - 14), (cx, cy + 14), (255, 255, 255), 1)
    banner = f"APD SENTINEL  mode {decision['mode']}  {fps:4.1f} fps"
    if decision.get("alarm"):
        banner += "  ALARM"
    cv2.rectangle(frame, (0, 0), (w, 26), (20, 20, 20), -1)
    cv2.putText(frame, banner, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return frame


# ---------------------------------------------------------------- main loop
class Runtime:
    def __init__(self, args):
        self.args = args
        self.shared = Shared()
        self.stop = threading.Event()
        self.link = None
        self.geom = CameraModel(hfov_deg=args.hfov, vfov_deg=args.vfov,
                                pan_sign=args.pan_sign, tilt_sign=args.tilt_sign)
        self.sound = args.sound
        self.tracker = Tracker()
        self.brain = Brain(DEFAULT_LIMITS, BrainConfig(patrol_interval=args.patrol,
                                                       alarm_delay=args.alarm_delay))
        self.camera = None
        self.perception = None
        self.manual = None             # (pan, tilt, until) from the dashboard
        self.paused = False
        self.events = []
        self.soc = None
        self.camera_state = ""
        self.volume = args.volume
        self.voice = None
        self.gestures = None
        self.interaction = None
        self.hands = []

    def event(self, text):
        self.events.append((time.strftime("%H:%M:%S"), text))
        del self.events[:-40]

    def pose(self):
        """Commanded servo pose at (roughly) capture time, from MCU telemetry."""
        if self.link is not None:
            tele = self.link.telemetry
            if tele is not None:
                return tele.pan, tele.tilt
        return self.brain.limits.phome, self.brain.limits.thome

    def run(self):
        import cv2
        from .interact import Interaction, InteractConfig
        from .vision import Perception, evidence, regions
        self.perception = Perception(imgsz=self.args.imgsz)
        self.interaction = Interaction(InteractConfig(assume_gloves=self.args.assume_gloves))
        try:
            from .gesture import GestureReader
            self.gestures = GestureReader()
            self.event("Model AI siap (pose + APD + gestur tangan)")
        except Exception as exc:                       # MediaPipe missing: run without gestures
            self.gestures = None
            self.event("Gestur tangan nonaktif: " + str(exc)[:60])
        if self.args.voice:
            from .voice import Voice
            self.voice = Voice(volume=self.volume / 100.0)
        last_seq, fps, n, t0 = -1, 0.0, 0, time.monotonic()
        prev_alarm, prev_mode = False, None
        while not self.stop.is_set():
            seq, stamp, frame = self.camera.read()
            now = time.monotonic()
            if self.link is not None:
                self.brain.set_limits(self.link.limits)
            if frame is None or seq == last_seq or now - stamp > 1.0:
                fault = self.camera.error if (frame is None or now - stamp > 2.5) and self.camera.error else None
                if fault and self.link is not None:
                    cmd, info = self.brain.step(now, [], fault=fault)
                    self.link.set_command(cmd)
                time.sleep(0.01)
                continue
            last_seq = seq
            pose = self.pose()
            scale = ANALYSIS_WIDTH / frame.shape[1]
            if scale < 1:
                frame = cv2.resize(frame, (ANALYSIS_WIDTH, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
            fh, fw = frame.shape[:2]
            people = self.perception.people(frame)
            ppe = self.perception.equipment(frame, people)
            dets = []
            for p in people:
                regs = regions(p, frame.shape)
                ev = evidence(p, regs, ppe, frame)
                dets.append(dict(angle_box=self.geom.box_to_angles(p.box, fw, fh, *pose),
                                 pixel_box=p.box, kps=p.kps, regions=regs, evidence=ev))
            # Hands only while someone is in view (MediaPipe costs ~90 ms per frame).
            hands_by_track = {}
            self.hands = []
            if people and self.gestures is not None:
                try:
                    self.hands = self.gestures.hands(frame, ppe)
                except Exception as exc:
                    self.event("Gestur error: " + str(exc)[:60])
                    self.hands = []
            self.tracker.update(dets, now)
            # People missed by ONE frame stay in the decision (0.4 s grace) so a
            # flickering detection cannot bounce the camera between modes.
            tracks = self.tracker.visible(now, max_age=0.4)
            if self.hands:
                from .gesture import owner
                fresh = [t for t in tracks if t.last_seen == now]
                for hnd in self.hands:
                    t = owner(hnd, fresh)
                    if t is None:
                        continue
                    hands_by_track.setdefault(t.tid, []).append(hnd)
                    glove = "PRESENT" if self.args.assume_gloves else hnd.glove
                    if glove != "UNKNOWN":
                        t.items["glove"].update(glove, 0.9, "DEBUG" if self.args.assume_gloves else hnd.glove_method,
                                                now, self.tracker.present_frames, self.tracker.absent_frames,
                                                self.tracker.evidence_ttl)
            fx, fx_id = self.interaction.update(now, tracks, hands_by_track,
                                                self.voice if self.sound else None)
            for note in self.interaction.events:
                self.event("Gestur: " + note)
            if self.paused:
                cmd, info = Command("I", *self.brain.aim, 30), dict(paused=True)
            elif self.manual and now < self.manual[2]:
                cmd, info = Command("T", self.manual[0], self.manual[1], 60), dict(manual=True)
            else:
                cmd, info = self.brain.step(now, tracks, pose=pose)
            # A bare-hand thumbs-up starts the alarm for that person (after the "no" shake).
            glove_alarm = cmd.trk and self.interaction.glove_alarm(cmd.trk) and cmd.mode in ("T", "G", "A", "V")
            locked = self.tracker.get(cmd.trk) if cmd.trk else None
            items = locked.item_code() if locked is not None else cmd.items
            alarm = cmd.alarm or bool(glove_alarm)
            mode = "V" if alarm else cmd.mode
            if alarm and not self.sound:
                info = dict(info, sound="MUTE")     # lock + LEDs/LCD stay, siren and relay stay OFF
            cmd = Command(mode, cmd.pan, cmd.tilt, cmd.spd, (items + "----")[:4], alarm and self.sound,
                          cmd.ppl, cmd.viol, cmd.trk, fx, fx_id, self.sound)
            if self.link is not None:
                self.link.set_command(cmd)
            alarm_now = (self.brain.alarm and cmd.mode == "V") or bool(glove_alarm)
            if alarm_now and not prev_alarm:
                self.event(f"ALARM: orang #{cmd.trk} APD tidak lengkap ({cmd.items})"
                           + ("" if self.sound else " [suara mati]"))
            if cmd.mode != prev_mode:
                self.event(f"Mode {prev_mode} -> {cmd.mode}")
            prev_alarm, prev_mode = alarm_now, cmd.mode
            n += 1
            if now - t0 >= 2:
                fps, n, t0 = n / (now - t0), 0, now
            decision = dict(mode=cmd.mode, alarm=alarm_now, sound=self.sound, volume=self.volume,
                            assume_gloves=self.args.assume_gloves, pan=cmd.pan, tilt=cmd.tilt,
                            items=cmd.items, lock=cmd.trk, people=cmd.ppl, violators=cmd.viol, info=info,
                            gestures=[dict(g=h.gesture, glove=h.glove) for h in self.hands])
            view = draw(frame.copy(), tracks, decision, None, fps, None, cmd.trk)
            for hnd in self.hands:
                x1, y1, x2, y2 = map(int, hnd.box)
                cv2.rectangle(view, (x1, y1), (x2, y2), (255, 160, 0), 2)
                cv2.putText(view, f"{hnd.gesture} sarung:{hnd.glove}", (x1, max(14, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 160, 0), 1)
            ok, jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 72])
            self.shared.publish(jpeg.tobytes() if ok else None, self.status(decision, tracks, fps, pose))

    def status(self, decision, tracks, fps, pose):
        link = self.link.snapshot() if self.link is not None else None
        tele = link["telemetry"] if link else None
        people = []
        for t in sorted(tracks, key=lambda t: t.tid):
            people.append(dict(id=t.tid, state=t.state(), locked=t.tid == decision["lock"],
                               items={i: dict(state=t.items[i].state, method=t.items[i].method,
                                              confidence=round(t.items[i].confidence, 2),
                                              visibility=t.regions[i].visibility if i in t.regions else "UNKNOWN",
                                              reason=t.regions[i].reason if i in t.regions else "")
                                      for i in ITEMS}))
        return dict(version=VERSION, time=time.strftime("%H:%M:%S"), decision=decision, fps=round(fps, 1),
                    camera=dict(source=str(self.args.camera), fps=round(self.camera.fps, 1),
                                error=self.camera.error, shape=list(self.camera.shape or [])),
                    pose=dict(pan=pose[0], tilt=pose[1]), people=people,
                    mcu=None if link is None else dict(
                        connected=link["connected"], status=link["status"], version=link["version"],
                        limits=link["limits"].__dict__ if link["limits"] else None,
                        telemetry=None if tele is None else dict(
                            pan=tele.pan, tilt=tele.tilt, moving=tele.moving, alarm=tele.sounding,
                            relay=tele.relay, lcd=tele.lcd_ok, clamped=tele.clamped, temp_a=tele.temp_a,
                            temp_p=tele.temp_p, fan_a=tele.fan_a, fan_p=tele.fan_p, vcc=tele.vcc_mv),
                        events=link["events"], errors=link["errors"]),
                    soc=self.soc, camera_state=self.camera_state, paused=self.paused,
                    events=self.events[-12:])


# ---------------------------------------------------------------- web
def make_handler(rt):
    html = (Path(__file__).with_name("dashboard.html")).read_bytes()

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

        def do_GET(self):
            if self.path == "/":
                return self._send(200, "text/html; charset=utf-8", html)
            if self.path == "/api/status":
                with rt.shared.lock:
                    data = json.dumps(rt.shared.status, default=str).encode()
                return self._send(200, "application/json", data)
            if self.path == "/stream.mjpg":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                last = -1
                try:
                    while not rt.stop.is_set():
                        with rt.shared.lock:
                            jpeg, seq = rt.shared.jpeg, rt.shared.jpeg_seq
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
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._send(400, "text/plain", b"bad json")
            action = body.get("action")
            if action == "pause":
                rt.paused = bool(body.get("value"))
            elif action == "aim":
                pan, tilt = rt.brain.limits.clamp(float(body["pan"]), float(body["tilt"]))
                rt.manual = (pan, tilt, time.monotonic() + 8)
            elif action == "sound":
                rt.sound = bool(body.get("value"))
                rt.event("Suara " + ("ON" if rt.sound else "OFF") + " (dari dashboard)")
            elif action == "volume":
                rt.volume = max(0, min(100, int(body.get("value", 50))))
                if rt.link is not None:
                    rt.link.set_volume(rt.volume)
                if rt.voice is not None:
                    rt.voice.volume = rt.volume / 100.0
                rt.event(f"Volume {rt.volume}%")
            elif action == "gloves":
                rt.args.assume_gloves = bool(body.get("value"))
                if rt.interaction is not None:
                    rt.interaction.cfg.assume_gloves = rt.args.assume_gloves
                rt.event("Debug sarung tangan: " + ("anggap DIPAKAI" if rt.args.assume_gloves else "deteksi asli"))
            elif action == "patrol":
                rt.brain.idle_since = rt.brain.last_people_at = -1e9
            elif action == "home":
                rt.manual = (rt.brain.limits.phome, rt.brain.limits.thome, time.monotonic() + 4)
            else:
                return self._send(400, "text/plain", b"unknown action")
            return self._send(200, "application/json", b'{"ok":true}')

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", default="luckfox", help="'luckfox', webcam index, or RTSP URL")
    ap.add_argument("--serial", default=None, help="adb serial of the Luckfox (if several devices)")
    ap.add_argument("--port", default="auto", help="Arduino COM port, 'auto' or 'none'")
    ap.add_argument("--http", type=int, default=8080)
    ap.add_argument("--imgsz", type=int, default=416)
    ap.add_argument("--config", default=str(ROOT / "config/sentinel.json"))
    ap.add_argument("--patrol", type=float, default=None, help="patrol interval seconds")
    ap.add_argument("--hfov", type=float, default=None)
    ap.add_argument("--vfov", type=float, default=None)
    ap.add_argument("--rotate", type=int, default=None, choices=(0, 90, 180, 270))
    ap.add_argument("--pan-sign", type=int, default=None, choices=(-1, 1))
    ap.add_argument("--tilt-sign", type=int, default=None, choices=(-1, 1))
    ap.add_argument("--sound", dest="sound", action="store_true", default=None,
                    help="siren ON (default comes from config: OFF)")
    ap.add_argument("--mute", dest="sound", action="store_false")
    ap.add_argument("--volume", type=int, default=None, help="speaker loudness 0..100 %%")
    ap.add_argument("--no-voice", dest="voice", action="store_false", default=True,
                    help="no greeting voice from the PC speaker")
    ap.add_argument("--assume-gloves", action="store_true", default=None,
                    help="DEBUG: treat every hand as gloved (test thumbs-up without gloves)")
    args = ap.parse_args(argv)
    cfg = {}
    if os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
    cam, srv, brn = cfg.get("camera", {}), cfg.get("servo", {}), cfg.get("brain", {})
    defaults = dict(patrol=brn.get("patrol_interval", 60.0), alarm_delay=brn.get("alarm_delay", 1.0),
                    hfov=cam.get("hfov_deg", 88.0), vfov=cam.get("vfov_deg", 52.0),
                    rotate=cam.get("rotate", 0), pan_sign=srv.get("pan_sign", -1),
                    tilt_sign=srv.get("tilt_sign", 1), sound=cfg.get("alarm_sound", False),
                    volume=cfg.get("volume", 50), assume_gloves=cfg.get("debug_assume_gloves", False))
    for key, value in defaults.items():
        if getattr(args, key, None) is None:
            setattr(args, key, value)
    print(f"Setelan: rotate={args.rotate} pan_sign={args.pan_sign} tilt_sign={args.tilt_sign} "
          f"suara={'ON' if args.sound else 'MATI'} volume={args.volume}% patroli={args.patrol:.0f}s "
          f"debug_sarung={'ON' if args.assume_gloves else 'off'}", flush=True)

    rt = Runtime(args)
    source = args.camera
    fox = None
    if args.camera == "luckfox":
        fox = Luckfox(args.serial)
        if not fox.present():
            print("Luckfox tidak terdeteksi lewat ADB. Colok USB lalu jalankan ulang.", flush=True)
            return 2
        for line in fox.prepare():
            print("Luckfox:", line, flush=True)
        source = RTSP_URL
    rt.camera = LatestFrame(source, rotate=args.rotate).start()
    if args.port != "none":
        port = args.port
        if port == "auto":
            import serial.tools.list_ports as lp
            found = [p.device for p in lp.comports() if (p.vid or 0) in (0x2341, 0x2A03, 0x1A86, 0x0403)]
            port = found[0] if found else None
            print("Arduino:", port or "tidak ditemukan (jalan tanpa servo)", flush=True)
        if port:
            from .link import SentinelLink
            rt.link = SentinelLink(port)
            rt.link.set_volume(args.volume)
            rt.link.start()
    server = ThreadingHTTPServer(("127.0.0.1", args.http), make_handler(rt))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Dashboard: http://127.0.0.1:{args.http}  (Ctrl+C untuk berhenti)", flush=True)

    if fox is not None:
        def camera_watchdog():
            """Every 5 s: heal a USB replug (forward lost), renew the 300 s on-board
            guard, re-apply the light profile after a reboot, read SoC temperature."""
            last_soc = 0.0
            while not rt.stop.wait(5):
                try:
                    if not fox.present():
                        rt.camera_state = "Pico tidak terhubung (USB)"
                        continue
                    if fox.ensure_forward():
                        rt.event("RTSP forward dipulihkan (Pico dicolok ulang?)")
                    if not fox.camera_running():
                        state = fox.ensure_profile()
                        if state == "APPLIED":
                            rt.event("Profil kamera ringan dipasang ulang")
                        reply = fox.start_camera()
                        last_line = reply.splitlines()[-1][:60] if reply else "tanpa balasan"
                        rt.event("Kamera Pico dinyalakan: " + last_line)
                    rt.camera_state = "OK"
                    now = time.monotonic()
                    if now - last_soc >= 10:
                        last_soc = now
                        soc = fox.soc_dc()
                        if soc is not None:
                            rt.soc = soc / 10
                            if rt.link is not None:
                                rt.link.set_env(soc)
                except Exception as exc:
                    rt.camera_state = "ADB: " + str(exc)[:80]
        threading.Thread(target=camera_watchdog, name="luckfox-watchdog", daemon=True).start()
    worker = threading.Thread(target=rt.run, daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        rt.stop.set()
        if rt.link is not None:
            rt.link.set_command(Command("I", rt.brain.limits.phome, rt.brain.limits.thome, 30))
            time.sleep(0.3)
            rt.link.stop()
        if rt.voice is not None:
            rt.voice.close()
        if rt.gestures is not None:
            rt.gestures.close()
        rt.camera.stop()
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
