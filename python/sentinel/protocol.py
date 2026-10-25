"""SLP/1 encoder/decoder (brain side). Pure functions, no I/O.

Mirrors arduino/apd_sentinel/sentinel_core.c byte for byte; the contract is
docs/sentinel/PROTOCOL.md. Angles are servo deci-degrees 0..1800.
"""
from dataclasses import dataclass
import re

BODY_MAX = 80
ITEM_CHARS = frozenset("PAU-")
MODES = frozenset("IPATGVSF")
_TOKEN = re.compile(r"[0-9A-F]{8}")


def crc8(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ (0x07 if value & 0x80 else 0)) & 0xFF
    return value


def frame(body: str) -> bytes:
    raw = body.encode("ascii")
    if not 1 <= len(raw) <= BODY_MAX or any(b < 0x20 or b > 0x7E or b in b"$*" for b in raw):
        raise ValueError("Invalid SLP/1 body: " + repr(body))
    return b"$" + raw + b"*" + f"{crc8(raw):02X}".encode() + b"\n"


def check_token(token: str) -> str:
    if not isinstance(token, str) or not _TOKEN.fullmatch(token) or token == "00000000":
        raise ValueError("Token must be 8 uppercase hex digits, not 00000000")
    return token


def hello(token):
    return frame("HELLO," + check_token(token))


def state(token, seq, cmd):
    """Encode one S frame from a sentinel.types.Command."""
    check_token(token)
    if not 1 <= seq <= 65535:
        raise ValueError("seq 1..65535")
    items = cmd.items if len(cmd.items) == 4 else cmd.items + "-"
    if cmd.mode not in MODES or len(items) != 4 or set(items) - ITEM_CHARS:
        raise ValueError("Invalid mode/items")
    if cmd.fx not in ("-", "N", "H", "C", "W") or type(cmd.fx_id) is not int or not 0 <= cmd.fx_id <= 255:
        raise ValueError("Invalid fx")
    if cmd.alarm and cmd.mode != "V":
        raise ValueError("alarm only in mode V")
    fields = (cmd.pan, cmd.tilt, cmd.spd, cmd.ppl, cmd.viol, cmd.trk)
    bounds = ((0, 1800), (0, 1800), (1, 600), (0, 99), (0, 99), (0, 65535))
    for value, (lo, hi) in zip(fields, bounds):
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError("S field out of range: " + repr(value))
    return frame(f"S,{token},{seq},{cmd.mode},{cmd.pan},{cmd.tilt},{cmd.spd},{items},"
                 f"{int(cmd.alarm)},{cmd.ppl},{cmd.viol},{cmd.trk},{cmd.fx},{cmd.fx_id},{int(cmd.vox)}")


def env(token, soc_dc):
    check_token(token)
    if type(soc_dc) is not int or not -400 <= soc_dc <= 1500:
        raise ValueError("soc_dc -400..1500")
    return frame(f"ENV,{token},{soc_dc}")


def simple(*fields):
    """PING/GETLIM/CAL/JOG/SET/SAVE/LOAD/DEFAULTS/FAN."""
    return frame(",".join(str(f) for f in fields))


class LineDecoder:
    """Incremental decoder for MCU output. Returns verified bodies; '#' console
    lines and junk are surfaced separately so a monitor can show them."""

    def __init__(self):
        self.buffer = bytearray()
        self.bad_crc = 0

    def feed(self, data: bytes):
        bodies, notes = [], []
        self.buffer.extend(data)
        while True:
            end = self.buffer.find(b"\n")
            if end < 0:
                if len(self.buffer) > 512:      # garbage without newline
                    self.buffer.clear()
                return bodies, notes
            line = bytes(self.buffer[:end]).rstrip(b"\r")
            del self.buffer[:end + 1]
            start = line.rfind(b"$")
            if start < 0:
                if line:
                    notes.append(line.decode("ascii", "replace"))
                continue
            raw = line[start + 1:]
            if len(raw) < 4 or raw[-3:-2] != b"*":
                self.bad_crc += 1
                continue
            body, digest = raw[:-3], raw[-2:]
            try:
                ok = int(digest, 16) == crc8(body) and digest == digest.upper()
            except ValueError:
                ok = False
            if ok:
                bodies.append(body.decode("ascii"))
            else:
                self.bad_crc += 1


@dataclass(frozen=True)
class Limits:
    pmin: int
    phome: int
    pmax: int
    tmin0: int
    tmin1: int
    thome: int
    tmax: int
    pvmax: int
    tvmax: int
    pacc: int
    tacc: int
    calibrated: bool = False

    def tilt_floor(self, pan):
        """Integer ceil formula from PROTOCOL.md section 5 (matches firmware)."""
        pan = min(max(int(pan), self.pmin), self.pmax)
        num = (self.tmin1 - self.tmin0) * (pan - self.pmin)
        den = self.pmax - self.pmin
        step = (num + den - 1) // den if num >= 0 else -((-num) // den)
        return self.tmin0 + step

    def clamp(self, pan, tilt):
        pan = min(max(int(round(pan)), self.pmin), self.pmax)
        tilt = min(max(int(round(tilt)), self.tilt_floor(pan)), self.tmax)
        return pan, tilt


DEFAULT_LIMITS = Limits(0, 900, 1450, 1450, 1000, 1800, 1800, 120, 90, 400, 300)


@dataclass(frozen=True)
class Telemetry:
    ms: int
    pan: int
    tilt: int
    pan_target: int
    tilt_target: int
    flags: int
    temp_a: float | None
    temp_p: float | None
    fan_a: int
    fan_p: int
    vcc_mv: int
    seq: int

    session = property(lambda s: bool(s.flags & 0x01))
    link_ok = property(lambda s: bool(s.flags & 0x02))
    sounding = property(lambda s: bool(s.flags & 0x04))
    relay = property(lambda s: bool(s.flags & 0x08))
    moving = property(lambda s: bool(s.flags & 0x10))
    cal_mode = property(lambda s: bool(s.flags & 0x20))
    lcd_ok = property(lambda s: bool(s.flags & 0x40))
    clamped = property(lambda s: bool(s.flags & 0x80))


def _temp(text):
    return None if text == "NA" else int(text) / 10.0


def parse(body: str):
    """Return (kind, payload). Unknown/malformed bodies -> ('UNKNOWN', body)."""
    f = body.split(",")
    try:
        if f[0] == "T" and len(f) == 13:
            return "T", Telemetry(int(f[1]), int(f[2]), int(f[3]), int(f[4]), int(f[5]),
                                  int(f[6], 16), _temp(f[7]), _temp(f[8]), int(f[9]),
                                  int(f[10]), int(f[11]), int(f[12]))
        if f[0] == "LIM" and len(f) == 13:
            v = [int(x) for x in f[1:]]
            return "LIM", Limits(*v[:11], calibrated=bool(v[11]))
        if f[0] == "READY" and len(f) == 5 and f[1] == "SENTINEL":
            return "READY", dict(version=f[2], token=f[3], calibrated=f[4] == "1")
        if f[0] == "PONG" and len(f) == 3:
            return "PONG", (int(f[1]), int(f[2]))
        if f[0] == "ACK" and len(f) == 4:
            return "ACK", dict(cmd=f[1], ok=f[2] == "OK", detail=f[3])
        if f[0] == "ERR" and len(f) == 2:
            return "ERR", f[1]
        if f[0] == "EVT" and len(f) >= 2:
            return "EVT", f[1:]
    except ValueError:
        pass
    return "UNKNOWN", body
