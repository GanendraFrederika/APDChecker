"""Offline/host policy reference. No camera, serial, or hardware side effects."""
from dataclasses import dataclass
import math

PPE_KINDS = ('glove', 'goggles', 'helmet', 'mask', 'shoes', 'vest')
OBSERVATIONS = frozenset(('VIOLATION', 'COMPLIANT', 'UNKNOWN', 'NO_PERSON',
                          'CAMERA_LOST', 'MODEL_ERROR', 'STARTING'))
FAULTS = frozenset(('CAMERA_LOST', 'MODEL_ERROR', 'STARTING'))

@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]

    def valid(self):
        if not isinstance(self.label, str):
            return False
        try:
            if len(self.box) != 4:
                return False
            x1, y1, x2, y2 = self.box
            return (all(math.isfinite(v) for v in (*self.box, self.confidence))
                    and 0 <= self.confidence <= 1 and x2 > x1 and y2 > y1)
        except (TypeError, ValueError):
            return False


def normal_label(label):
    return label.lower().strip().replace('-', '_').replace(' ', '_')


def validate_required(required):
    items = tuple(normal_label(k) for k in required)
    if not items or len(set(items)) != len(items) or any(k not in PPE_KINDS for k in items):
        raise ValueError('Required PPE must be a nonempty, unique subset of ' + str(PPE_KINDS))
    return items


def assess(people, equipment, required=('helmet', 'mask'), min_confidence=0.4):
    """Attach evidence to one person. Missing/ambiguous evidence is UNKNOWN.

    Explicit no_* can assert a violation. Conflicting positive/negative evidence
    for the same required item is UNKNOWN for that person unless a different
    required item has unambiguous negative evidence. This geometry is NOT tracking.
    """
    required = validate_required(required)
    if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError('Confidence threshold must be in [0, 1]')
    people = list(people)
    invalid_people = sum(not p.valid() for p in people)
    people = [p for p in people if p.valid() and p.confidence >= min_confidence
              and normal_label(p.label) == 'person']
    assigned = [set() for _ in people]
    unassigned = 0
    invalid = 0
    for item in equipment:
        if not item.valid():
            invalid += 1
            continue
        if item.confidence < min_confidence:
            continue
        label = normal_label(item.label)
        kind = label.removeprefix('no_')
        if kind not in required:
            continue
        cx = (item.box[0] + item.box[2]) / 2
        cy = (item.box[1] + item.box[3]) / 2
        candidates = []
        for i, person in enumerate(people):
            x1, y1, x2, y2 = person.box
            relative_y = (cy - y1) / (y2 - y1)
            if not (x1 <= cx <= x2 and y1 <= cy <= y2):
                continue
            if kind in ('helmet', 'mask', 'goggles') and relative_y > 0.55:
                continue
            if kind == 'shoes' and relative_y < 0.5:
                continue
            candidates.append(i)
        if len(candidates) == 1:
            assigned[candidates[0]].add(label)
        else:
            unassigned += 1
    rows = []
    for index, labels in enumerate(assigned):
        conflicts = sorted(k for k in required if k in labels and 'no_' + k in labels)
        present = sorted(k for k in required if k in labels and k not in conflicts)
        negative = sorted(k for k in required if 'no_' + k in labels and k not in conflicts)
        missing = sorted(set(required) - set(present))
        state = 'VIOLATION' if negative else ('UNKNOWN' if missing else 'COMPLIANT')
        rows.append(dict(index=index + 1, state=state, present=present,
                         missing_evidence=missing, explicit_missing=negative,
                         conflicting_evidence=conflicts, box=list(people[index].box)))
    if any(r['state'] == 'VIOLATION' for r in rows):
        overall = 'VIOLATION'
    elif any(r['state'] == 'UNKNOWN' for r in rows) or unassigned or invalid or invalid_people:
        overall = 'UNKNOWN'
    elif rows:
        overall = 'COMPLIANT'
    else:
        overall = 'NO_PERSON'
    return dict(observation=overall, people=rows, people_count=len(rows),
                violator_count=sum(r['state'] == 'VIOLATION' for r in rows),
                unassigned_equipment=unassigned, invalid_equipment=invalid, invalid_people=invalid_people,
                required=list(required))


class Debouncer:
    """Both elapsed time and fresh samples required; fault is never SAFE.

    UNKNOWN retains a prior alarm indication but resets its confirmation timer.
    A caller must provide fresh inference timestamps, never re-feed cached frames.
    """
    def __init__(self, violation_seconds=1.5, clear_seconds=3.0, min_samples=3,
                 max_gap=2.0):
        if (not all(math.isfinite(v) and v >= 0 for v in
                    (violation_seconds, clear_seconds)) or
                not math.isfinite(max_gap) or max_gap <= 0 or
                not isinstance(min_samples, int) or min_samples < 1):
            raise ValueError('Invalid debounce settings')
        self.violation_seconds = violation_seconds
        self.clear_seconds = clear_seconds
        self.min_samples = min_samples
        self.max_gap = max_gap
        self.alarm = False
        self.candidate = None
        self.since = None
        self.samples = 0
        self.previous = None

    def update(self, observation, now):
        if observation not in OBSERVATIONS or not math.isfinite(now):
            raise ValueError('Invalid observation/timestamp')
        if self.previous is not None and now <= self.previous:
            raise ValueError('Each observation needs a strictly increasing timestamp')
        if self.previous is not None and now - self.previous > self.max_gap:
            self.candidate = None
            self.samples = 0
        self.previous = now
        if observation in FAULTS:
            self.alarm = False
            self.candidate = None
            self.samples = 0
            return self.alarm
        target = (True if observation == 'VIOLATION' else
                  False if observation in ('COMPLIANT', 'NO_PERSON') else None)
        if target is None:
            self.candidate = None
            self.samples = 0
            return self.alarm
        if target != self.candidate:
            self.candidate = target
            self.since = now
            self.samples = 1
        else:
            self.samples += 1
        delay = self.violation_seconds if target else self.clear_seconds
        if self.samples >= self.min_samples and now - self.since >= delay:
            self.alarm = target
        return self.alarm
