"""Latest-frame camera reader. A background thread drains the stream so the AI
always analyses the NEWEST frame (an RTSP buffer would otherwise add seconds of
lag and make the servo chase the past)."""
import math
import os
import threading
import time


def roll_zoom(roll, w, h, cap=1.3):
    """Zoom that hides the black corners after leveling a picture rotated by `roll`
    degrees (capped: a big tilt keeps small black corners instead of losing the view)."""
    if abs(roll) < 1.5:
        return 1.0
    a = math.radians(abs(roll))
    need = max((w * math.cos(a) + h * math.sin(a)) / w, (w * math.sin(a) + h * math.cos(a)) / h)
    return min(cap, need)


def zoomed_fov(fov_deg, zoom):
    """Field of view left after a digital zoom."""
    return math.degrees(2 * math.atan(math.tan(math.radians(fov_deg) / 2) / zoom))


def open_capture(source):
    import cv2
    if isinstance(source, str) and not source.isdecimal():
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG,
                               [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
    else:
        cap = cv2.VideoCapture(int(source), cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


class LatestFrame:
    def __init__(self, source, rotate=0, roll=0.0):
        self.source = source
        self.rotate = rotate
        self.roll = roll                 # small extra CW tilt of the tube (degrees)
        self._lock = threading.Lock()
        self._frame = None               # RAW decoded frame (no rotation yet)
        self._stamp = 0.0
        self._seq = 0
        self._cache = (None, None, None)  # (seq, rotate/roll key, processed frame)
        self._stop = threading.Event()
        self.error = ""
        self.fps = 0.0
        self.shape = None
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=3)

    def read(self):
        """(seq, capture_monotonic_time, frame) of the newest frame, or (0, 0, None).

        Rotation and roll leveling run HERE, once per frame the AI actually uses (3-5 fps),
        not in the reader thread: that thread must drain the stream at the full camera
        rate or the RTSP buffer grows and the servo chases a picture from the past."""
        with self._lock:
            seq, stamp, raw = self._seq, self._stamp, self._frame
            cseq, ckey, cframe = self._cache
        if raw is None:
            return seq, stamp, None
        key = (self.rotate, self.roll)
        if cseq == seq and ckey == key:
            return seq, stamp, cframe
        frame = self._process(raw, *key)
        with self._lock:
            self._cache = (seq, key, frame)
        self.shape = frame.shape
        return seq, stamp, frame

    @staticmethod
    def _process(frame, rotate, roll, max_side=1440):
        import cv2
        code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(rotate)
        if code is not None:
            frame = cv2.rotate(frame, code)
        if abs(roll) >= 1.5:
            # Level a tilted tube: rotate about the centre and zoom to hide corners. The
            # output is capped at `max_side` px (the AI analyses <= 1152 px wide anyway).
            h, w = frame.shape[:2]
            s = min(1.0, max_side / max(w, h))
            ow, oh = int(w * s), int(h * s)
            m = cv2.getRotationMatrix2D((w / 2, h / 2), -roll, roll_zoom(roll, w, h) * s)
            m[0, 2] += (ow - w) / 2
            m[1, 2] += (oh - h) / 2
            frame = cv2.warpAffine(frame, m, (ow, oh), flags=cv2.INTER_LINEAR)
        return frame

    def set_rotate(self, degrees, roll=None):
        """Change the rotation live (dashboard button / auto-orientation / calibration)."""
        if degrees not in (0, 90, 180, 270):
            raise ValueError("rotate must be 0, 90, 180 or 270")
        self.rotate = degrees
        if roll is not None:
            self.roll = float(roll)

    def _run(self):
        while not self._stop.is_set():
            cap = open_capture(self.source)
            if not cap.isOpened():
                self.error = "Kamera tidak bisa dibuka: " + str(self.source)
                cap.release()
                self._stop.wait(2.0)
                continue
            self.error = ""
            count, t0 = 0, time.monotonic()
            while not self._stop.is_set():
                ok, frame = cap.read()
                now = time.monotonic()
                if not ok or frame is None:
                    self.error = "Frame kamera hilang (stream putus?)"
                    break
                with self._lock:
                    self._frame, self._stamp = frame, now
                    self._seq += 1
                count += 1
                if now - t0 >= 2.0:
                    self.fps, count, t0 = count / (now - t0), 0, now
            cap.release()
            self._stop.wait(1.0)
