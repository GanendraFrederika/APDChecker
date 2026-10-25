"""PPE1 status for the v2.2 legacy receiver, NOT APD3. No serial imports/I/O.

Wire: !PPE,V,3*HH\n; XOR of ASCII PPE,V,3; mask 1 helmet, 2 shoes, 4 vest.
"""
from dataclasses import dataclass
import math

ITEM_BITS = {"helmet": 1, "shoes": 2, "vest": 4}
STATES = frozenset("VCNUF")


def encode_status(state, mask=0):
    if not isinstance(state, str) or state not in STATES or isinstance(mask, bool) or not isinstance(mask, int):
        raise ValueError("Invalid PPE1 status/mask")
    if not 0 <= mask <= 7 or (state == "V") != (mask != 0):
        raise ValueError("Only V uses a nonzero item mask")
    body = f"PPE,{state},{mask}".encode("ascii")
    checksum = 0
    for byte in body:
        checksum ^= byte
    return b"!" + body + f"*{checksum:02X}\n".encode("ascii")


def decode_status(packet):
    if not isinstance(packet, bytes) or len(packet) != 12 or not packet.startswith(b"!PPE,"):
        raise ValueError("Invalid PPE1 packet")
    try:
        state, digit = chr(packet[5]), chr(packet[7])
        if digit not in "01234567":
            raise ValueError("Invalid mask")
        mask = int(digit)
        if encode_status(state, mask) != packet:
            raise ValueError("Invalid checksum/framing")
    except (UnicodeError, IndexError) as exc:
        raise ValueError("Invalid PPE1 packet") from exc
    return state, mask


@dataclass(frozen=True)
class Decision:
    state: str
    mask: int = 0


def report_decision(report):
    """Union of explicit, person-associated negatives, not missing detections.

    Multiple people: any confirmed missing item contributes its indicator.
    A lack of vest support/detection is UNKNOWN, never automatically no_vest.
    """
    observation = report.get("observation")
    if observation in ("CAMERA_LOST", "MODEL_ERROR", "STARTING"):
        return Decision("F")
    if observation == "VIOLATION":
        mask = 0
        for person in report.get("people", []):
            if person.get("state") == "VIOLATION":
                for item in person.get("explicit_missing", []):
                    mask |= ITEM_BITS.get(item, 0)
        return Decision("V", mask) if mask else Decision("U")
    if observation == "COMPLIANT":
        # Defend against a caller feeding a report for only helmet/mask.
        required = set(ITEM_BITS)
        people = report.get("people", [])
        if (set(report.get("required", [])) == required and people and
                all(p.get("state") == "COMPLIANT" and
                    required <= set(p.get("present", [])) for p in people)):
            return Decision("C")
        return Decision("U")
    if observation == "NO_PERSON":
        return Decision("N") if not report.get("people") else Decision("U")
    return Decision("U")


class DecisionFilter:
    """Debounce each mask, not only a boolean alarm; unknown never clears a latch."""
    def __init__(self, violation_seconds=1.5, clear_seconds=3.0, min_samples=3, max_gap=2.0):
        values = (violation_seconds, clear_seconds, max_gap)
        if (not all(math.isfinite(v) and v >= 0 for v in values) or max_gap == 0 or
                isinstance(min_samples, bool) or not isinstance(min_samples, int) or min_samples < 1):
            raise ValueError("Invalid timing")
        self.violation_seconds = violation_seconds
        self.clear_seconds = clear_seconds
        self.min_samples = min_samples
        self.max_gap = max_gap
        self.previous = None
        self.candidate = None
        self.since = 0.0
        self.samples = 0
        self.confirmed = Decision("U")

    def update(self, report, now):
        if not math.isfinite(now) or (self.previous is not None and now <= self.previous):
            raise ValueError("Fresh increasing timestamps required")
        if self.previous is not None and now - self.previous > self.max_gap:
            self.candidate = None
            self.samples = 0
            self.confirmed = Decision("U")
        self.previous = now
        decision = report_decision(report)
        if decision.state in "UF":
            self.candidate = None
            self.samples = 0
            self.confirmed = Decision("U")
            return decision
        if decision != self.candidate:
            self.candidate, self.since, self.samples = decision, now, 1
        else:
            self.samples += 1
        delay = self.violation_seconds if decision.state == "V" else self.clear_seconds
        if self.samples >= self.min_samples and now - self.since >= delay:
            self.confirmed = decision
        # Pending changes explicitly say unknown; MCU retains an already latched alarm.
        return decision if self.confirmed == decision else Decision("U")
