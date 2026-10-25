"""Bounded, conservative HOST prototype; no camera, model, serial or GPIO IO.

IoU is short-term geometric association, NOT biometric identity/re-identification.
Missing/ambiguous associations discard evidence rather than transferring it.
Visibility must come from a separately validated body-region/occlusion adapter.
"""
from dataclasses import dataclass, field
import math
from .rules import Detection, FAULTS, normal_label, validate_required

PRODUCTION_REQUIRED = ('vest', 'shoes', 'helmet')
INDICATOR_COLORS = {'vest': 'green', 'shoes': 'yellow', 'helmet': 'red'}
VISIBILITY = frozenset(('OBSERVABLE', 'NOT_VISIBLE', 'UNKNOWN'))


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class TrackingSettings:
    required: tuple = PRODUCTION_REQUIRED
    confidence: float = 0.4
    match_iou: float = 0.3
    overlap_fraction: float = 0.2
    present_seconds: float = 0.25
    absent_seconds: float = 1.5
    present_samples: int = 2
    absent_samples: int = 3
    evidence_ttl_seconds: float = 2.0
    lost_ttl_seconds: float = 1.0
    max_gap_seconds: float = 0.75
    max_frame_age_seconds: float = 0.75
    max_tracks: int = 8
    max_equipment: int = 64

    def __post_init__(self):
        object.__setattr__(self, 'required', validate_required(self.required))
        for name in ('confidence', 'match_iou', 'overlap_fraction'):
            value = getattr(self, name)
            if not _finite_number(value) or not 0 < value <= 1:
                raise ValueError('Invalid ' + name)
        for name in ('present_seconds', 'absent_seconds', 'evidence_ttl_seconds',
                     'lost_ttl_seconds', 'max_gap_seconds', 'max_frame_age_seconds'):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid ' + name)
        for name in ('present_samples', 'absent_samples', 'max_tracks', 'max_equipment'):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError('Invalid ' + name)
        if self.present_samples < 2 or self.absent_samples < 2:
            raise ValueError('A single frame cannot confirm an item')
        if self.max_tracks > 32 or self.max_equipment > 256:
            raise ValueError('Prototype capacity exceeds bounded limits')


@dataclass
class ItemMemory:
    state: str = 'UNKNOWN'
    observed_at: float | None = None
    confidence: float | None = None
    candidate: str | None = None
    since: float | None = None
    samples: int = 0
    previous_sample: float | None = None

    def expire(self, now, ttl):
        if self.observed_at is not None and now - self.observed_at >= ttl:
            self.state = 'UNKNOWN'
            self.observed_at = None
            self.confidence = None

    def observe(self, raw, confidence, now, cfg):
        self.expire(now, cfg.evidence_ttl_seconds)
        if raw in ('UNKNOWN', 'CONFLICT'):
            self.candidate = None
            self.samples = 0
            self.since = self.previous_sample = None
            if raw == 'CONFLICT':
                self.state, self.observed_at, self.confidence = 'UNKNOWN', None, None
            return
        # Opposing fresh evidence invalidates the old conclusion immediately.
        if self.state not in ('UNKNOWN', raw):
            self.state, self.observed_at, self.confidence = 'UNKNOWN', None, None
        if (raw != self.candidate or self.previous_sample is None or
                now - self.previous_sample > cfg.max_gap_seconds):
            self.candidate, self.since, self.samples = raw, now, 1
        else:
            self.samples += 1
        self.previous_sample = now
        seconds = cfg.present_seconds if raw == 'PRESENT' else cfg.absent_seconds
        samples = cfg.present_samples if raw == 'PRESENT' else cfg.absent_samples
        if self.samples >= samples and now - self.since >= seconds:
            self.state = raw
        if self.state == raw:
            self.observed_at, self.confidence = now, confidence


@dataclass
class Track:
    track_id: int
    box: tuple
    last_seen: float
    items: dict = field(default_factory=dict)


def _intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(a):
    return (a[2] - a[0]) * (a[3] - a[1])


def _iou(a, b):
    intersection = _intersection(a, b)
    return intersection / (_area(a) + _area(b) - intersection)


def model_capabilities(labels, required=PRODUCTION_REQUIRED):
    labels = {normal_label(label) for label in labels}
    required = validate_required(required)
    missing_positive = [kind for kind in required if kind not in labels]
    missing_negative = ['no_' + kind for kind in required if 'no_' + kind not in labels]
    return dict(label_contract_supported=not (missing_positive or missing_negative),
                missing_positive=missing_positive, missing_negative=missing_negative,
                accuracy_validated=False, deployment_ready=False)


class PersonPPETracker:
    def __init__(self, settings=None):
        self.settings = settings or TrackingSettings()
        self.tracks = {}
        self.next_id = 1
        self.previous_time = None
        self.previous_frame_id = None
        self.camera_view_epoch = 0

    def _flush(self):
        self.tracks.clear()

    def _reject(self, message):
        self._flush()
        raise ValueError(message)

    def invalidate_camera_view(self, camera_view_epoch):
        """Call BEFORE a move/view change, including when no new frame exists.

        Returns a replacement report; callers must discard any old report and
        queued frames. Epoch is capture-time metadata, not inference-time pose.
        No identity/PPE memory may bridge this boundary. Track IDs/time checks
        deliberately remain monotonic. This does not control a servo.
        """
        if (type(camera_view_epoch) is not int or
                not self.camera_view_epoch < camera_view_epoch < 2**64):
            self._reject('View invalidation requires a strictly newer uint64 epoch')
        self._flush()
        self.camera_view_epoch = camera_view_epoch
        return self._report([], 'STARTING', reason='CAMERA_VIEW_CHANGED')

    def _new_track(self, person, now):
        track = Track(self.next_id, person.box, now,
                      {kind: ItemMemory() for kind in self.settings.required})
        self.next_id += 1
        return track

    def _report(self, people, observation=None, selected_track_id=None, **extra):
        if observation is None:
            states = {p['state'] for p in people}
            observation = ('VIOLATION' if 'VIOLATION' in states else
                           'UNKNOWN' if 'UNKNOWN' in states else
                           'COMPLIANT' if people else 'NO_PERSON')
        selected = None
        mode = 'NO_PERSON' if not people else 'MULTIPLE_PEOPLE'
        if selected_track_id is not None:
            selected = next((p for p in people if p['track_id'] == selected_track_id), None)
            mode = 'SELECTED_TRACK' if selected else 'TARGET_NOT_VISIBLE'
        elif len(people) == 1:
            selected, mode = people[0], 'SINGLE_PERSON'
        lights = {kind: None for kind in self.settings.required}
        if selected:
            lights = {kind: (True if item['state'] == 'PRESENT' else
                             False if item['state'] == 'ABSENT' else None)
                      for kind, item in selected['items'].items()}
        return dict(observation=observation, people=people,
                    alarm_candidate=any(p['alarm_candidate'] for p in people),
                    indicators=dict(mode=mode, track_id=selected['track_id'] if selected else None,
                                    colors={k: INDICATOR_COLORS.get(k) for k in lights},
                                    lights=lights, physical_behavior_finalized=False),
                    hardware_outputs_enabled=False, camera_view_epoch=self.camera_view_epoch, **extra)

    def update(self, frame_id, captured_at, people=(), equipment=(), *,
               visibility=None, received_at=None, fault=None, selected_track_id=None,
               camera_view_epoch=0, camera_view_unstable=False):
        """visibility keys are CURRENT detection indices, not track IDs.

        camera_view_epoch/camera_view_unstable metadata must describe the EXPOSURE view,
        including motion during exposure. Default epoch 0/stable is fixed-camera
        compatibility only, never a safe implicit default for a moving backend.
        Each value maps item -> OBSERVABLE / NOT_VISIBLE / UNKNOWN. Omitting it
        is UNKNOWN: a box inside the image is NOT sufficient proof of visibility.
        no_* only counts with OBSERVABLE. Positive evidence never comes from a
        missing detection. Returning alarm_candidate is a SIMULATED decision,
        never an actuator request. Frames carry independent capture IDs/times.
        """
        cfg = self.settings
        if (type(camera_view_epoch) is not int or
                not self.camera_view_epoch <= camera_view_epoch < 2**64):
            self._reject('Invalid/backwards camera view epoch; cache invalidated')
        if type(camera_view_unstable) is not bool:
            self._reject('Invalid camera view stability flag; cache invalidated')
        if type(frame_id) is not int or frame_id < 0:
            self._reject('Invalid capture frame ID')
        if self.previous_frame_id is not None and frame_id <= self.previous_frame_id:
            self._reject('Repeated/backwards frame ID; cache invalidated')
        if not _finite_number(captured_at) or captured_at < 0:
            self._reject('Invalid capture timestamp')
        if self.previous_time is not None and captured_at <= self.previous_time:
            self._reject('Repeated/backwards capture timestamp; cache invalidated')
        received_at = captured_at if received_at is None else received_at
        if (not _finite_number(received_at) or
                not 0 <= received_at - captured_at <= cfg.max_frame_age_seconds):
            self._reject('Stale/future captured frame; cache invalidated')
        if selected_track_id is not None and (type(selected_track_id) is not int or selected_track_id < 1):
            self._reject('Invalid selected track ID')
        if fault is not None and (not isinstance(fault, str) or fault not in FAULTS):
            self._reject('Unsupported fault')
        now = captured_at
        if self.previous_time is not None and now - self.previous_time > cfg.max_gap_seconds:
            self._flush()
        self.previous_time, self.previous_frame_id = now, frame_id
        if camera_view_epoch != self.camera_view_epoch:
            self._flush()
            self.camera_view_epoch = camera_view_epoch
        if fault:
            self._flush()
            return self._report([], fault, selected_track_id)
        if camera_view_unstable:
            self._flush()
            return self._report([], 'STARTING', selected_track_id,
                                reason='CAMERA_MOVING_OR_SETTLING')
        people, equipment = list(people), list(equipment)
        if (len(people) > cfg.max_tracks or len(equipment) > cfg.max_equipment or
                any(not isinstance(p, Detection) or not p.valid() or normal_label(p.label) != 'person' for p in people) or
                any(not isinstance(p, Detection) or not p.valid() for p in equipment)):
            self._flush()
            return self._report([], 'MODEL_ERROR', selected_track_id, reason='INVALID_OR_OVER_CAPACITY')
        visibility = {} if visibility is None else visibility
        if (not isinstance(visibility, dict) or
                any(type(i) is not int or not 0 <= i < len(people) or not isinstance(row, dict) or
                    any(k not in cfg.required or not isinstance(v, str) or v not in VISIBILITY for k, v in row.items())
                    for i, row in visibility.items())):
            self._reject('Invalid body visibility metadata')
        # Keep visibility aligned to original indices while dropping weak people.
        pairs = [(p, visibility.get(i, {})) for i, p in enumerate(people) if p.confidence >= cfg.confidence]
        people = [p for p, _ in pairs]
        visible = [v for _, v in pairs]
        old = {tid: t for tid, t in self.tracks.items() if now - t.last_seen < cfg.lost_ttl_seconds}
        candidates = {i: [tid for tid, t in old.items() if _iou(p.box, t.box) >= cfg.match_iou]
                      for i, p in enumerate(people)}
        old_candidates = {tid: [i for i in candidates if tid in candidates[i]] for tid in old}
        uncertain = set()
        for i, p in enumerate(people):
            if len(candidates[i]) > 1 or any(len(old_candidates[tid]) > 1 for tid in candidates[i]):
                uncertain.add(i)
            for j in range(i):
                if _intersection(p.box, people[j].box) / min(_area(p.box), _area(people[j].box)) >= cfg.overlap_fraction:
                    uncertain.update((i, j))
        # An ambiguous old track is retired, not saved for a later unsafe match.
        retired = {tid for i in uncertain for tid in candidates[i]}
        matched = set()
        current = []
        for i, person in enumerate(people):
            ids = candidates[i]
            if i not in uncertain and len(ids) == 1 and ids[0] not in retired:
                track = old[ids[0]]
                matched.add(track.track_id)
            else:
                track = self._new_track(person, now)
            track.box, track.last_seen = person.box, now
            current.append(track)
        # If a person wasn't detected in even one inference frame, its evidence
        # is erased. A brief reacquisition may reuse an ID, never its PPE cache.
        retained = {tid: t for tid, t in old.items() if tid not in matched and tid not in retired}
        for track in retained.values():
            track.items = {kind: ItemMemory() for kind in cfg.required}
        # Active people have priority over invisible retained track handles.
        retained = dict(list(retained.items())[:max(0, cfg.max_tracks - len(current))])
        self.tracks = {**retained, **{t.track_id: t for t in current}}
        assigned = [{kind: {'PRESENT': [], 'ABSENT': []} for kind in cfg.required} for _ in people]
        unassigned = 0
        for item in equipment:
            if item.confidence < cfg.confidence:
                continue
            label = normal_label(item.label)
            kind = label.removeprefix('no_')
            if kind not in cfg.required:
                continue
            cx, cy = (item.box[0]+item.box[2])/2, (item.box[1]+item.box[3])/2
            possible = []
            for i, person in enumerate(people):
                x1, y1, x2, y2 = person.box
                y = (cy-y1)/(y2-y1)
                if not (x1 <= cx <= x2 and y1 <= cy <= y2):
                    continue
                if kind == 'helmet' and y > 0.55 or kind == 'shoes' and y < 0.5:
                    continue
                if kind == 'vest' and not 0.15 <= y <= 0.8:
                    continue
                possible.append(i)
            if len(possible) != 1 or possible[0] in uncertain:
                unassigned += 1
                continue
            i = possible[0]
            assigned[i][kind]['ABSENT' if label.startswith('no_') else 'PRESENT'].append(item.confidence)
        reports = []
        for i, track in enumerate(current):
            items = {}
            for kind, memory in track.items.items():
                seen = assigned[i][kind]
                region = visible[i].get(kind, 'UNKNOWN')
                raw, reason, confidence = 'UNKNOWN', 'NO_EVIDENCE', None
                if i in uncertain:
                    reason = 'IDENTITY_AMBIGUOUS'
                elif region == 'NOT_VISIBLE':
                    reason = 'NOT_VISIBLE'
                elif seen['PRESENT'] and seen['ABSENT']:
                    raw, reason = 'CONFLICT', 'CONFLICTING_DETECTIONS'
                elif seen['PRESENT']:
                    raw, reason, confidence = 'PRESENT', 'POSITIVE_DETECTION', max(seen['PRESENT'])
                elif seen['ABSENT'] and region == 'OBSERVABLE':
                    raw, reason, confidence = 'ABSENT', 'EXPLICIT_NEGATIVE_VISIBLE', max(seen['ABSENT'])
                elif seen['ABSENT']:
                    reason = 'NEGATIVE_VISIBILITY_UNVERIFIED'
                previous_state, previous_observed_at = memory.state, memory.observed_at
                memory.observe(raw, confidence, now, cfg)
                transition = None
                if previous_state != memory.state:
                    if memory.state == 'PRESENT':
                        cause = 'POSITIVE_CONFIRMED'
                    elif memory.state == 'ABSENT':
                        cause = 'NEGATIVE_CONFIRMED'
                    elif raw == 'CONFLICT':
                        cause = 'CONFLICTING_EVIDENCE'
                    elif raw in ('PRESENT', 'ABSENT') and raw != previous_state:
                        cause = 'OPPOSING_EVIDENCE'
                    elif previous_observed_at is not None and now - previous_observed_at >= cfg.evidence_ttl_seconds:
                        cause = 'EVIDENCE_EXPIRED'
                    else:
                        cause = 'EVIDENCE_INVALIDATED'
                    transition = dict(previous=previous_state, current=memory.state, cause=cause)
                fresh = memory.observed_at == now and memory.state == raw
                items[kind] = dict(state=memory.state, observation=raw, reason=reason,
                                   visibility=region, source='FRESH' if fresh else 'CACHED' if memory.state != 'UNKNOWN' else 'NONE',
                                   observed_at=memory.observed_at,
                                   expires_at=memory.observed_at+cfg.evidence_ttl_seconds if memory.observed_at is not None else None,
                                   confidence=memory.confidence, candidate=memory.candidate,
                                   candidate_samples=memory.samples, transition=transition)
            states = {v['state'] for v in items.values()}
            state = ('VIOLATION' if 'ABSENT' in states else 'COMPLIANT' if states == {'PRESENT'} else 'UNKNOWN')
            reports.append(dict(track_id=track.track_id, box=list(track.box), state=state,
                                identity_ambiguous=i in uncertain, items=items,
                                alarm_candidate=any(v['state'] == 'ABSENT' and v['source'] == 'FRESH' for v in items.values())))
        uncertain_overall = 'UNKNOWN' if unassigned and not any(p['state'] == 'VIOLATION' for p in reports) else None
        return self._report(reports, observation=uncertain_overall, selected_track_id=selected_track_id,
                            unassigned_equipment=unassigned,
                            retained_track_count=len(self.tracks))
