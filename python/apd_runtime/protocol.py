"""APD2 transport, disabled unless firmware is verified out of band.

WARNING: a legacy one-byte sketch can interpret characters INSIDE an APD2 frame
as relay commands. HELLO probing is NOT safe firmware detection. Never open a
legacy/unknown port with this transport.
"""
import re
import threading
import time


def crc8(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ (0x07 if value & 0x80 else 0)) & 0xff
    return value


def encode_frame(sequence, *fields):
    if (not 1 <= sequence <= 65535 or not fields or
            any(not re.fullmatch(r'[A-Z0-9_]+', f) for f in fields)):
        raise ValueError('Invalid frame fields')
    payload = (str(sequence) + ',' + ','.join(fields)).encode('ascii')
    return b'@' + payload + b'*' + f'{crc8(payload):02X}'.encode() + b'\n'


def decode_frame(raw):
    if len(raw) > 100:
        raise ValueError('Frame too long')
    raw = raw.rstrip(b'\r\n')
    match = re.fullmatch(rb'@([0-9]+(?:,[A-Z0-9_]+)+)\*([0-9A-F]{2})', raw)
    if not match or crc8(match[1]) != int(match[2], 16):
        raise ValueError('Invalid frame/checksum')
    fields = match[1].decode().split(',')
    sequence = int(fields.pop(0))
    if not 1 <= sequence <= 65535:
        raise ValueError('Invalid sequence')
    return sequence, fields


class ActuatorLink:
    """Reserved for a future verified APD2 MCU, not existing v1.9 firmware.

    firmware_verified must only be set AFTER uploading/inspecting APD2 firmware,
    verifying relay polarity, and checking its hardware watchdog. The flag is an
    operator assertion, NOT automatic device attestation. No auto-reconnect/arm.
    """
    def __init__(self, port=None, enabled=False, firmware_verified=False):
        self.port = port
        self.enabled = enabled
        self.firmware_verified = firmware_verified
        self.armed = False
        self.connected = False
        self.error = None
        self.last_ack = None
        self._serial = None
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._alarm = False
        self._sent_alarm = None
        self._thread = None

    def status(self):
        with self._lock:
            return dict(enabled=self.enabled, port=self.port, connected=self.connected,
                        armed=self.armed, error=self.error, last_ack=self.last_ack,
                        firmware_verified=self.firmware_verified)

    def start(self):
        with self._lock:
            if not self.enabled:
                return
            if not self.firmware_verified:
                self.error = 'BLOCKED: firmware must be verified APD2 out of band; no probing v1.9'
                return
            if not self.port:
                self.error = 'No explicitly selected Arduino port'
                return
            if self._thread is not None:
                raise RuntimeError('Link already started; create a new link to retry')
            self._thread = threading.Thread(target=self._run, daemon=True, name='arduino-link')
            self._thread.start()

    def _request(self, command):
        self._seq = self._seq % 65535 + 1
        self._serial.write(encode_frame(self._seq, command))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            raw = self._serial.readline(100)
            if not raw:
                continue
            try:
                seq, fields = decode_frame(raw)
            except ValueError:
                continue
            if seq != self._seq or len(fields) != 3 or fields[:2] != ['ACK', command]:
                continue
            if fields[2] == 'FAULT':
                raise RuntimeError('Arduino reports FAULT')
            expected = {'A': ('ALARM',), 'S': ('IDLE',), 'HELLO': ('IDLE',),
                        'H': ('ALARM', 'IDLE')}[command]
            if fields[2] not in expected:
                raise RuntimeError('Unexpected MCU output state')
            with self._lock:
                self.last_ack = fields[2]
            return
        raise TimeoutError('No valid APD2 ACK; outputs require MCU watchdog')

    def _run(self):
        try:
            import serial
            self._serial = serial.Serial(self.port, 9600, timeout=0.1, write_timeout=1)
            if self._stop.wait(2.0):
                return
            self._serial.reset_input_buffer()
            self._request('HELLO')
            with self._lock:
                self.connected = True
            while not self._stop.is_set():
                with self._lock:
                    desired = self.armed and self._alarm
                if desired != self._sent_alarm:
                    self._request('A' if desired else 'S')
                    self._sent_alarm = desired
                else:
                    self._request('H')
                self._stop.wait(0.4)
        except Exception as exc:
            with self._lock:
                self.error = str(exc)
                self.armed = False
        finally:
            if self._serial:
                try:
                    self._request('S')
                except Exception:
                    pass
                self._serial.close()
            with self._lock:
                self.connected = False
                self.armed = False

    def set_alarm(self, active):
        with self._lock:
            self._alarm = bool(active)

    def arm(self):
        with self._lock:
            if (not self.enabled or not self.firmware_verified or
                    not self.connected or self.error or self._stop.is_set()):
                raise RuntimeError('Arduino APD2 is not connected/validated')
            self.armed = True

    def disarm(self):
        with self._lock:
            self.armed = False
            self._alarm = False

    def stop(self):
        self.disarm()
        self._stop.set()
        if self._thread:
            self._thread.join(3)
