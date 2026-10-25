"""Decision state machine: where the camera looks and what the MCU shows.

Modes (wire letters):
  I home     nobody seen; camera rests at home and waits for the next patrol
  P patrol   every `patrol_interval` s: left, right, left, right, left, centre
  A acquire  first frames on a new person (short confirm before committing)
  T track    lock ONE person and follow while their PPE is inspected
  G group    2+ people: frame them all (each is inspected while visible)
  V violation lock the confirmed violator; siren after `alarm_delay` s
  S search   lock target lost: hold, then sweep back toward last motion
  F fault    camera/model failure

Priority: an alarmed violator stays locked even when others walk in.
"""
from dataclasses import dataclass
import math

from .types import Command


@dataclass
class BrainConfig:
    patrol_interval: float = 60.0
    patrol_speed: int = 30            # deg/s: smooth, deliberate sweep
    track_speed: int = 70             # calm follow; the MCU eases every start/stop
    acquire_frames: int = 2
    alarm_delay: float = 1.0          # confirmed violation must persist this long
    lost_hold: float = 1.5            # stay on last position before searching
    search_time: float = 4.0
    deadband_dd: int = 60             # person within +-6 deg of centre: do not move
    settle_dd: int = 20               # once moving, re-centre to within 2 deg, then rest
    aim_alpha: float = 0.35           # low-pass on the aim point (kills box jitter)
    lead_s: float = 0.25              # aim ahead of a walking person (latency comp)
    group_margin_dd: int = 60


class Brain:
    def __init__(self, limits, cfg=None):
        self.cfg = cfg or BrainConfig()
        self.limits = limits
        self.mode = "I"
        self.lock_id = 0
        self.alarm = False
        self.last_people_at = -1e9
        self.idle_since = 0.0
        self.patrol_points = []
        self.patrol_index = 0
        self.acquire_count = 0
        self.lost_since = None
        self.last_target = None          # (pan, tilt, vel)
        self.aim = (limits.phome, limits.thome)
        self.search_points = []
        self.group_since = None
        self.filt = None                 # low-passed raw aim point
        self.recentering = False

    def set_limits(self, limits):
        self.limits = limits

    # ------------------------------------------------------------ helpers
    def _patrol_route(self):
        L = self.limits
        span = L.pmax - L.pmin
        left = L.pmax - int(0.08 * span)          # pan max = camera LEFT on this rig
        right = L.pmin + int(0.08 * span)
        tilt = L.thome
        route = [(left, tilt), (right, tilt), (left, tilt), (right, tilt), (left, tilt),
                 (L.phome, L.thome)]
        return [L.clamp(p, t) for p, t in route]

    def _aim_at(self, track, now):
        cx, cy = track.center
        vx, vy = track.vel
        cx += vx * self.cfg.lead_s
        cy += vy * self.cfg.lead_s
        # Frame the upper body slightly above centre so head AND feet stay in view.
        box_h = track.box[1] - track.box[3]       # tilt_top - tilt_bottom (dd)
        cy += 0.05 * box_h
        return self._smooth(cx, cy)

    def _smooth(self, pan, tilt):
        """Calm camera: filter the aim point, then move only when the person leaves a
        +-6 deg dead zone; once moving, re-centre fully (to +-2 deg) and rest again.
        Tiny 1-2 cm shifts of a standing person therefore never move the servo."""
        a = self.cfg.aim_alpha
        if self.filt is None:
            self.filt = (pan, tilt)
        else:
            self.filt = (self.filt[0] + a * (pan - self.filt[0]), self.filt[1] + a * (tilt - self.filt[1]))
        fp, ft = self.filt
        ap, at = self.aim
        err = max(abs(fp - ap), abs(ft - at))
        if self.recentering:
            if err <= self.cfg.settle_dd:
                self.recentering = False
        elif err > self.cfg.deadband_dd:
            self.recentering = True
        if self.recentering:
            self.aim = self.limits.clamp(fp, ft)
        return self.aim

    def _group_aim(self, tracks):
        pl = min(t.box[0] for t in tracks)
        pr = max(t.box[2] for t in tracks)
        tt = max(t.box[1] for t in tracks)
        tb = min(t.box[3] for t in tracks)
        return self._smooth((pl + pr) / 2, (tt + tb) / 2)

    # ------------------------------------------------------------ main step
    def step(self, now, tracks, fault=None, pose=None):
        """tracks: currently visible Track objects. pose: (pan, tilt) from MCU."""
        cfg, L = self.cfg, self.limits
        if fault:
            self.mode, self.alarm = "F", False
            return Command("F", *self.aim, 30, "---", False, 0, 0, 0), dict(reason=fault)

        visible = {t.tid: t for t in tracks}
        violators = [t for t in tracks if t.state() == "VIOLATION"]
        if tracks:
            self.last_people_at = now

        # 1. Keep an existing violation lock as long as that person is visible.
        locked = visible.get(self.lock_id) if self.lock_id else None
        if locked is not None:
            self.lost_since = None
            self.last_target = (locked.center, locked.vel)
        if locked is not None and locked.state() == "VIOLATION":
            pan, tilt = self._aim_at(locked, now)
            confirmed = locked.violation_since is not None and now - locked.violation_since >= cfg.alarm_delay
            self.mode, self.alarm = "V", confirmed
            return self._cmd("V", pan, tilt, cfg.track_speed, locked, tracks, violators), dict(lock=locked.tid)

        # 2. A new violator takes priority over everything else.
        if violators:
            target = min(violators, key=lambda t: t.violation_since or now)
            self.lock_id = target.tid
            pan, tilt = self._aim_at(target, now)
            self.mode = "V"
            self.alarm = now - (target.violation_since or now) >= cfg.alarm_delay
            return self._cmd("V", pan, tilt, cfg.track_speed, target, tracks, violators), dict(lock=target.tid)
        self.alarm = False

        # 3. Several people: frame the group so every visible person gets inspected.
        # Hysteresis: a 2nd person must be seen for 0.6 s before leaving a single lock.
        if len(tracks) >= 2:
            self.group_since = self.group_since if self.group_since is not None else now
        else:
            self.group_since = None
        locked_single = self.lock_id in visible and self.mode in ("A", "T")
        if len(tracks) >= 2 and locked_single and now - self.group_since < 0.6:
            t = visible[self.lock_id]
            pan, tilt = self._aim_at(t, now)
            return self._cmd("T", pan, tilt, cfg.track_speed, t, tracks, violators), dict(lock=t.tid)
        if len(tracks) >= 2:
            self.lock_id = 0
            pan, tilt = self._group_aim(tracks)
            self.mode = "G"
            focus = min(tracks, key=lambda t: t.inspected_frames)   # least-inspected person
            return self._cmd("G", pan, tilt, cfg.track_speed, focus, tracks, violators), dict(group=len(tracks))

        # 4. Exactly one person: acquire, then lock and inspect.
        if len(tracks) == 1:
            t = tracks[0]
            if self.lock_id != t.tid:
                self.lock_id = t.tid
                self.acquire_count = 0
            self.acquire_count += 1
            mode = "A" if self.acquire_count <= cfg.acquire_frames else "T"
            pan, tilt = self._aim_at(t, now)
            self.mode = mode
            return self._cmd(mode, pan, tilt, cfg.track_speed, t, tracks, violators), dict(lock=t.tid)

        # 5. Nobody visible: briefly hold/search where the lock disappeared.
        if self.lock_id and self.last_target is not None:
            if self.lost_since is None:
                self.lost_since = now
            lost_for = now - self.lost_since
            if lost_for < cfg.lost_hold + cfg.search_time:
                (cx, cy), (vx, vy) = self.last_target
                if lost_for >= cfg.lost_hold:      # curious robot: peek ahead, then glance back
                    k = (lost_for - cfg.lost_hold) / cfg.search_time
                    ahead = (1 if vx >= 0 else -1) * max(120.0, min(300.0, abs(vx) * 1.5))
                    if k < 0.55:
                        cx += ahead * min(1.0, k / 0.35)
                    else:
                        cx -= 0.6 * ahead * min(1.0, (k - 0.55) / 0.3)
                pan, tilt = L.clamp(cx, cy)
                self.aim = (pan, tilt)
                self.mode = "S"
                return Command("S", pan, tilt, 35, "UUUU", False, 0, 0, self.lock_id), dict(search=round(lost_for, 1))
            self.lock_id, self.last_target, self.lost_since = 0, None, None
            self.idle_since = now
            self.filt, self.recentering = None, False

        # 6. Patrol every interval (interrupted at once by any detection above).
        if self.mode != "P" and now - max(self.idle_since, self.last_people_at) >= cfg.patrol_interval:
            self.patrol_points, self.patrol_index = self._patrol_route(), 0
            self.mode = "P"
        if self.mode == "P":
            target = self.patrol_points[self.patrol_index]
            if pose is not None and abs(pose[0] - target[0]) <= 8 and abs(pose[1] - target[1]) <= 8:
                self.patrol_index += 1
                if self.patrol_index >= len(self.patrol_points):
                    self.mode, self.idle_since = "I", now
                    self.aim = (L.phome, L.thome)
                    return Command("I", L.phome, L.thome, cfg.patrol_speed), dict(patrol="done")
                target = self.patrol_points[self.patrol_index]
            self.aim = target
            return Command("P", target[0], target[1], cfg.patrol_speed), dict(
                patrol=f"{self.patrol_index + 1}/{len(self.patrol_points)}")
        if self.mode not in ("I",):
            self.idle_since = now
        self.mode = "I"
        self.aim = (L.phome, L.thome)
        wait = cfg.patrol_interval - (now - max(self.idle_since, self.last_people_at))
        return Command("I", L.phome, L.thome, 40), dict(next_patrol=max(0.0, wait))

    def _cmd(self, mode, pan, tilt, spd, focus, tracks, violators):
        items = focus.item_code() if focus is not None else "---"
        return Command(mode, int(pan), int(tilt), spd, items, self.alarm and mode == "V",
                       min(99, len(tracks)), min(99, len(violators)), focus.tid if focus else 0)
