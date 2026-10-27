"""Serial link to the Sentinel MCU. One background thread owns the port.

The brain calls `set_command()` whenever it has a new decision; the thread sends
the latest command at a steady 10 Hz (fresh seq every time), reads telemetry and
re-handshakes automatically after an MCU reset or a USB replug.
Opening the Uno port resets the board, so the link waits for READY first.

Opening the port RESETS the Uno (DTR). So a transient USB error (servo current spike
on a shared 5 V rail, Windows "ClearCommError") must NOT close and reopen the port:
that turned every glitch into a full Arduino reboot (26-10-2026). The session keeps
the port open and retries; only a port that is really gone is reopened.
"""
import secrets
import threading
import time

from . import protocol
from .types import Command

SEND_PERIOD = 0.1
READY_TIMEOUT = 4.0
IO_RETRY = 8                # consecutive I/O errors tolerated before the port is reopened


class SentinelLink:
    def __init__(self, port, baud=115200, serial_factory=None, clock=time.monotonic):
        self.port = port
        self.baud = baud
        self._factory = serial_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._command = Command("I", 900, 1800, 60)
        self._volume = None
        self._env = None
        self._pending = []                  # one-shot bodies (CAL/JOG/SET/...)
        self.token = None
        self.seq = 0
        self.connected = False
        self.limits = protocol.DEFAULT_LIMITS
        self.telemetry = None
        self.telemetry_at = 0.0
        self.version = None
        self.lcd = None                     # (row0, row1) exactly as shown on the 16x2 LCD
        self.events = []                    # recent (time, text), bounded
        self.event_total = 0                # events ever logged (to find new ones)
        self.errors = {}
        self.status = "STARTING"
        self.io_glitches = 0                # transient serial errors survived (USB / power)
        self.resets = 0                     # MCU reboots seen while connected

    # ------------------------------------------------------------ public API
    def start(self):
        self._thread = threading.Thread(target=self._run, name="sentinel-link", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def set_command(self, command: Command):
        with self._lock:
            self._command = command

    def set_env(self, soc_dc):
        with self._lock:
            self._env = soc_dc

    def set_volume(self, percent):
        """Speaker loudness 0..100 %, re-sent after every (re)connect."""
        with self._lock:
            self._volume = max(0, min(100, int(percent)))
            if self.connected:
                self._pending.append(protocol.simple("VOL", self._volume))

    def send_raw(self, *fields):
        """Queue a non-session command, e.g. send_raw('CAL', 1)."""
        with self._lock:
            self._pending.append(protocol.simple(*fields))

    def snapshot(self):
        with self._lock:
            return dict(connected=self.connected, status=self.status, port=self.port,
                        version=self.version, limits=self.limits, telemetry=self.telemetry, lcd=self.lcd,
                        telemetry_age=(self._clock() - self.telemetry_at) if self.telemetry else None,
                        events=list(self.events[-12:]), errors=dict(self.errors))

    # ------------------------------------------------------------ internals
    def _event(self, text):
        with self._lock:
            self.events.append((time.strftime("%H:%M:%S"), text))
            del self.events[:-50]
            self.event_total += 1

    def _open(self):
        if self._factory is not None:
            return self._factory(self.port, self.baud, timeout=0.02, write_timeout=0.5)
        import serial
        # DTR/RTS low BEFORE opening: the Uno's auto-reset circuit only fires on DTR,
        # so (re)connecting no longer reboots the Arduino and the servos do not jump.
        s = serial.Serial()
        s.port, s.baudrate, s.timeout, s.write_timeout = self.port, self.baud, 0.02, 0.5
        s.dtr = False
        s.rts = False
        s.open()
        return s

    def _io(self, op, *args):
        """Serial read/write that survives short glitches without closing the port."""
        for attempt in range(IO_RETRY):
            try:
                return op(*args)
            except Exception as exc:        # pyserial SerialException / OSError on Windows
                if "could not open port" in str(exc) or "FileNotFound" in str(exc):
                    raise
                with self._lock:
                    self.io_glitches += 1
                if attempt == 0:
                    self._event("USB serial gangguan sesaat: " + str(exc)[:60])
                self._stop.wait(0.05 * (attempt + 1))
        raise RuntimeError("Port serial tidak pulih")

    def _handle(self, body):
        kind, payload = protocol.parse(body)
        with self._lock:
            if kind == "T":
                self.telemetry, self.telemetry_at = payload, self._clock()
            elif kind == "LIM":
                self.limits = payload
            elif kind == "LCD":
                self.lcd = payload
            elif kind == "READY":
                self.version = payload["version"]
        if kind == "ERR":
            with self._lock:
                self.errors[payload] = self.errors.get(payload, 0) + 1
        elif kind in ("EVT", "ACK", "READY"):
            self._event(body)
        return kind, payload

    def _handshake(self, stream, decoder):
        """Wait for boot READY (port open resets the Uno), then HELLO."""
        deadline = self._clock() + READY_TIMEOUT
        booted = False
        while self._clock() < deadline and not self._stop.is_set():
            bodies, _ = decoder.feed(self._io(stream.read, 256))
            for body in bodies:
                kind, payload = self._handle(body)
                if kind == "READY" or kind == "T":
                    booted = True
            if booted:
                break
        if not booted:
            raise RuntimeError("Sentinel firmware tidak menjawab (READY). Sudah upload apd_sentinel.ino?")
        self.token = secrets.token_hex(4).upper()
        if self.token == "00000000":
            self.token = "5E471E1A"
        self.seq = 0
        self._io(stream.write, protocol.hello(self.token))
        deadline = self._clock() + 2.0
        while self._clock() < deadline and not self._stop.is_set():
            bodies, _ = decoder.feed(self._io(stream.read, 256))
            for body in bodies:
                kind, payload = self._handle(body)
                if kind == "READY" and payload["token"] == self.token:
                    return
        raise RuntimeError("HELLO tidak dijawab dengan token yang benar")

    def _session(self, stream, decoder):
        self._handshake(stream, decoder)
        with self._lock:
            self.connected, self.status = True, "CONNECTED"
            if self._volume is not None:
                self._pending.append(protocol.simple("VOL", self._volume))
        self._event("Terhubung ke " + self.port)
        next_send = self._clock()
        while not self._stop.is_set():
            bodies, _ = decoder.feed(self._io(stream.read, 256))
            for body in bodies:
                kind, payload = self._handle(body)
                if kind == "READY" and payload["token"] == "00000000":
                    with self._lock:
                        self.resets += 1
                    return True             # MCU rebooted: same port, new handshake
            with self._lock:
                pending, self._pending = self._pending, []
                command, env = self._command, self._env
            for packet in pending:
                self._io(stream.write, packet)
            now = self._clock()
            if now >= next_send:
                next_send = max(next_send + SEND_PERIOD, now)
                tele = self.telemetry
                if tele is not None and tele.cal_mode:
                    continue        # brain must not fight a calibration session
                self.seq = self.seq % 65535 + 1
                self._io(stream.write, protocol.state(self.token, self.seq, command))
                if env is not None and self.seq % 10 == 0:
                    self._io(stream.write, protocol.env(self.token, env))
            if self.telemetry_at and now - self.telemetry_at > 3.0:
                raise RuntimeError("Telemetri MCU berhenti")
        return False

    def _run(self):
        while not self._stop.is_set():
            stream = None
            try:
                with self._lock:
                    self.status = "OPENING " + self.port
                stream = self._open()
                decoder = protocol.LineDecoder()
                # A reboot seen on an open port is re-handshaken WITHOUT reopening it
                # (reopening would reset the Uno once more).
                while self._session(stream, decoder) and not self._stop.is_set():
                    with self._lock:
                        self.connected, self.status = False, "MCU reboot - handshake ulang"
                    self._event("Arduino reboot terdeteksi (tegangan servo?) - sambung ulang tanpa reset")
            except Exception as exc:          # serial errors, replug, reset
                with self._lock:
                    self.connected = False
                    self.status = "ERROR: " + str(exc)[:120]
                    self.telemetry_at = 0.0
                self._event("Link: " + str(exc)[:120])
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            self._stop.wait(1.5)
