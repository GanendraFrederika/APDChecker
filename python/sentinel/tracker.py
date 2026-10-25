"""Multi-person tracker with per-person PPE memory.

Positions are kept in SERVO-ANGLE space (deci-degrees), not pixels: when the
camera pans, a person who stands still keeps the same coordinates, so IDs
survive camera motion. Association = greedy by IoU in angle space plus centre
distance, with a constant-velocity prediction for walking people.

Per item state machine (debounced, conservative):
  UNKNOWN --(>= present_frames PRESENT within window)--> PRESENT
  UNKNOWN --(>= absent_frames ABSENT within window)----> ABSENT
  Opposite evidence first resets to UNKNOWN; unknown frames never flip a state,
  and evidence older than ttl decays to UNKNOWN (occlusion is not "missing").
"""
from dataclasses import dataclass, field
import math

ITEMS = ("helmet", "vest", "shoes", "glove")
REQUIRED = ("helmet", "vest", "shoes")        # glove is optional: shown, never alarmed


@dataclass
class ItemState:
    state: str = "UNKNOWN"
    candidate: str | None = None
    count: int = 0
    last_seen: float = 0.0        # time of last PRESENT/ABSENT evidence
    method: str = ""
    confidence: float = 0.0

    def update(self, raw, conf, method, now, present_frames, absent_frames, ttl):
        if self.state != "UNKNOWN" and now - self.last_seen > ttl:
            self.state, self.candidate, self.count = "UNKNOWN", None, 0
        if raw == "UNKNOWN":
            return
        self.method, self.confidence = method, conf
        if self.state != "UNKNOWN" and raw != self.state:
            self.state = "UNKNOWN"                      # opposing evidence: re-verify
        if raw == self.candidate:
            self.count += 1
        else:
            self.candidate, self.count = raw, 1
        need = present_frames if raw == "PRESENT" else absent_frames
        if self.count >= need:
            self.state = raw
        if self.state == raw:
            self.last_seen = now


@dataclass
class Track:
    tid: int
    box: tuple                     # angle-space box (pan_l, tilt_t, pan_r, tilt_b), dd
    pixel_box: tuple
    vel: tuple = (0.0, 0.0)        # dd/s of the centre
    first_seen: float = 0.0
    last_seen: float = 0.0
    hits: int = 0
    items: dict = field(default_factory=lambda: {k: ItemState() for k in ITEMS})
    evidence: dict = field(default_factory=dict)
    regions: dict = field(default_factory=dict)
    kps: object = None
    violation_since: float | None = None
    inspected_frames: int = 0

    @property
    def center(self):
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2

    def predicted_center(self, now):
        dt = min(1.0, max(0.0, now - self.last_seen))
        cx, cy = self.center
        return cx + self.vel[0] * dt, cy + self.vel[1] * dt

    def state(self):
        states = [self.items[k].state for k in REQUIRED]
        if "ABSENT" in states:
            return "VIOLATION"
        if all(s == "PRESENT" for s in states):
            return "COMPLIANT"
        return "CHECKING"

    def item_code(self):
        return "".join({"PRESENT": "P", "ABSENT": "A"}.get(self.items[k].state, "U") for k in ITEMS)


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class Tracker:
    def __init__(self, max_age=1.2, min_iou=0.15, present_frames=3, absent_frames=4,
                 evidence_ttl=4.0, max_tracks=12):
        self.tracks: dict[int, Track] = {}
        self.next_id = 1
        self.max_age = max_age
        self.min_iou = min_iou
        self.present_frames = present_frames
        self.absent_frames = absent_frames
        self.evidence_ttl = evidence_ttl
        self.max_tracks = max_tracks

    def update(self, detections, now):
        """detections: list of dicts {angle_box, pixel_box, kps, evidence, regions}."""
        live = {tid: t for tid, t in self.tracks.items() if now - t.last_seen <= self.max_age}
        pairs = []
        for di, d in enumerate(detections):
            box = d["angle_box"]
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            diag = math.hypot(box[2] - box[0], box[3] - box[1]) or 1.0
            for tid, t in live.items():
                px, py = t.predicted_center(now)
                shifted = (t.box[0] + px - t.center[0], t.box[1] + py - t.center[1],
                           t.box[2] + px - t.center[0], t.box[3] + py - t.center[1])
                iou = _iou(box, shifted)
                dist = math.hypot(cx - px, cy - py) / diag
                if iou >= self.min_iou or dist < 0.6:
                    pairs.append((iou - 0.5 * dist, di, tid))
        pairs.sort(reverse=True)
        used_d, used_t, matched = set(), set(), {}
        for _, di, tid in pairs:
            if di in used_d or tid in used_t:
                continue
            used_d.add(di)
            used_t.add(tid)
            matched[di] = tid
        for di, d in enumerate(detections):
            if di in matched:
                t = live[matched[di]]
                dt = max(1e-3, now - t.last_seen)
                ocx, ocy = t.center
                ncx = (d["angle_box"][0] + d["angle_box"][2]) / 2
                ncy = (d["angle_box"][1] + d["angle_box"][3]) / 2
                a = 0.5                                          # velocity smoothing
                t.vel = (a * (ncx - ocx) / dt + (1 - a) * t.vel[0], a * (ncy - ocy) / dt + (1 - a) * t.vel[1])
            else:
                if len(live) >= self.max_tracks:
                    continue
                t = Track(self.next_id, d["angle_box"], d["pixel_box"], first_seen=now)
                self.next_id += 1
                live[t.tid] = t
            t.box, t.pixel_box, t.last_seen = d["angle_box"], d["pixel_box"], now
            t.hits += 1
            t.kps, t.regions, t.evidence = d.get("kps"), d.get("regions", {}), d.get("evidence", {})
            for item, (raw, conf, method) in t.evidence.items():
                t.items[item].update(raw, conf, method, now, self.present_frames,
                                     self.absent_frames, self.evidence_ttl)
            if any(e[0] != "UNKNOWN" for e in t.evidence.values()):
                t.inspected_frames += 1
            if t.state() == "VIOLATION":
                t.violation_since = t.violation_since or now
            else:
                t.violation_since = None
        self.tracks = live
        return [t for t in live.values() if t.last_seen == now]

    def get(self, tid):
        return self.tracks.get(tid)

    def visible(self, now, max_age=0.0):
        return [t for t in self.tracks.values() if now - t.last_seen <= max_age + 1e-9]
