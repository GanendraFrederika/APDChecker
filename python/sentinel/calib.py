"""Camera orientation calibration from servo motion (no person needed).

Turn the camera a few degrees with the servos and measure how the picture shifts
(phase correlation). With a correctly oriented picture:
  pan  +  (camera turns LEFT on this rig)  -> the scene slides RIGHT (+x)
  tilt +  (camera looks UP)                -> the scene slides DOWN  (+y)
The measured directions give the total picture rotation (any angle: 90-degree steps
for the sensor mounting plus the small "roll" of the tube), and the shift sizes give
the field of view. One measurement replaces guessing rotate / hfov / vfov by hand.
"""
import math
import time

import numpy as np

MOVE_DD = 50                       # 5 degrees each way: big enough to measure, small overlap loss
BASE = (900, 1650)                 # front, slightly down: allowed on every rig zone


def shift(a, b):
    """(dx, dy, response): how far the content of frame `b` moved relative to `a`."""
    import cv2
    win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(np.float32(a), np.float32(b), win)
    return dx, dy, resp


def prep(frame, width=480):
    import cv2
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    k = width / g.shape[1]
    g = cv2.resize(g, (width, int(g.shape[0] * k)), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(g, (3, 3), 0), k


def _wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


def solve(v_pan, v_tilt, dpan_deg, dtilt_deg, size, current_total, zoom_now=1.0):
    """Orientation from the two measured image shifts (pixels, current picture).

    v_pan: shift for +dpan, v_tilt: shift for +dtilt. size: (w, h) of the current picture.
    current_total: rotation already applied (rotate + roll, CW degrees).
    zoom_now: digital zoom of the current picture (roll leveling); the returned FOV is
    the BASE field of view of the upright picture without that zoom.
    Returns dict(rotate, roll, hfov, vfov, agree_deg, ok, why)."""
    ang_p = math.degrees(math.atan2(v_pan[1], v_pan[0]))       # y down: angle is clockwise
    ang_t = math.degrees(math.atan2(v_tilt[1], v_tilt[0]))
    corr_p = _wrap(0.0 - ang_p)                                # extra CW rotation that makes
    corr_t = _wrap(90.0 - ang_t)                               # pan -> right, tilt -> down
    agree = abs(_wrap(corr_p - corr_t))
    # circular mean of the two estimates
    corr = math.degrees(math.atan2(math.sin(math.radians(corr_p)) + math.sin(math.radians(corr_t)),
                                   math.cos(math.radians(corr_p)) + math.cos(math.radians(corr_t))))
    total = (current_total + corr) % 360.0
    rotate = int(round(total / 90.0)) % 4 * 90
    roll = _wrap(total - rotate)
    # Field of view along the corrected axes. The picture is rotated by `corr` more,
    # so swap width/height when that is closer to a quarter turn.
    w, h = size
    if int(round(corr / 90.0)) % 2:
        w, h = h, w
    fx = math.hypot(*v_pan) / math.tan(math.radians(dpan_deg)) / zoom_now
    fy = math.hypot(*v_tilt) / math.tan(math.radians(dtilt_deg)) / zoom_now
    hfov = 2 * math.degrees(math.atan((w / 2) / fx)) if fx > 0 else None
    vfov = 2 * math.degrees(math.atan((h / 2) / fy)) if fy > 0 else None
    ok, why = True, "OK"
    if agree > 25:
        ok, why = False, f"arah pan dan tilt tidak konsisten ({agree:.0f} derajat)"
    elif min(math.hypot(*v_pan), math.hypot(*v_tilt)) < 4:
        ok, why = False, "gambar hampir tidak bergeser (servo tidak bergerak / kamera beku?)"
    return dict(rotate=rotate, roll=round(roll, 1), hfov=hfov and round(hfov, 1), vfov=vfov and round(vfov, 1),
                agree_deg=round(agree, 1), correction=round(corr, 1), ok=ok, why=why)


def run(rt, log=print):
    """Drive the servos through rt.manual, read frames from rt.camera, apply the result."""
    link = rt.link
    if link is None or not link.connected:
        return dict(ok=False, why="Arduino tidak terhubung")

    def settle_and_grab(pan, tilt):
        rt.manual = (pan, tilt, time.monotonic() + 30)
        t_end = time.monotonic() + 8
        while time.monotonic() < t_end:
            tele = link.telemetry
            if tele and abs(tele.pan - pan) <= 3 and abs(tele.tilt - tilt) <= 3 and not tele.moving:
                break
            time.sleep(0.05)
        still = time.monotonic()
        time.sleep(0.9)                          # RTSP + decoder latency: frames after the stop
        frames = []
        t_end = time.monotonic() + 3
        while len(frames) < 2 and time.monotonic() < t_end:
            seq, stamp, frame = rt.camera.read()
            if frame is not None and stamp > still + 0.6 and (not frames or seq != frames[-1][0]):
                frames.append((seq, frame))
            time.sleep(0.03)
        return [f for _, f in frames]

    # Measure on the picture WITHOUT the roll leveling: its black corners stand still
    # while the scene moves and would pull the phase correlation toward zero shift.
    saved_roll = rt.camera.roll
    rt.camera.set_rotate(rt.args.rotate, 0.0)
    try:
        return _measure(rt, settle_and_grab, saved_roll)
    finally:
        if rt.camera.roll == 0.0 and saved_roll:
            rt.camera.set_rotate(rt.args.rotate, saved_roll)      # failed: keep the old leveling


def _measure(rt, settle_and_grab, saved_roll):
    p0, t0 = BASE
    shots = {}
    for key, (p, t) in dict(pl=(p0 - MOVE_DD, t0), pr=(p0 + MOVE_DD, t0),
                            tl=(p0, t0 - MOVE_DD), th=(p0, t0 + MOVE_DD)).items():
        frames = settle_and_grab(p, t)
        if len(frames) < 2:
            rt.manual = None
            return dict(ok=False, why="kamera tidak mengirim gambar baru")
        shots[key] = frames
    rt.manual = (p0, t0, time.monotonic() + 3)
    a, k = prep(shots["pl"][1])
    b, _ = prep(shots["pr"][1])
    c, _ = prep(shots["tl"][1])
    d, _ = prep(shots["th"][1])
    n1, _ = prep(shots["pl"][0])
    noise = shift(n1, a)
    sp = shift(a, b)                             # pan +16 degrees
    st = shift(c, d)                             # tilt +16 degrees
    v_pan = (sp[0] / k, sp[1] / k)
    v_tilt = (st[0] / k, st[1] / k)
    h, w = shots["pl"][1].shape[:2]
    res = solve(v_pan, v_tilt, 2 * MOVE_DD / 10, 2 * MOVE_DD / 10, (w, h), rt.args.rotate)
    res.update(v_pan=[round(v, 1) for v in v_pan], v_tilt=[round(v, 1) for v in v_tilt],
               response=[round(sp[2], 3), round(st[2], 3)], still_noise=round(math.hypot(noise[0], noise[1]) / k, 1))
    if res["ok"] and min(sp[2], st[2]) < 0.03:
        res.update(ok=False, why="gambar kurang bertekstur untuk diukur (arahkan ke dinding/ruang yang ramai)")
    return res
