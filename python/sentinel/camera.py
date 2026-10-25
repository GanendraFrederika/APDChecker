"""Latest-frame camera reader. A background thread drains the stream so the AI
always analyses the NEWEST frame (an RTSP buffer would otherwise add seconds of
lag and make the servo chase the past)."""
import os
import threading
import time


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
    def __init__(self, source, rotate=0):
        self.source = source
        self.rotate = rotate
        self._lock = threading.Lock()
        self._frame = None
        self._stamp = 0.0
        self._seq = 0
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
        """(seq, capture_monotonic_time, frame) of the newest frame, or (0, 0, None)."""
        with self._lock:
            return self._seq, self._stamp, self._frame

    def _run(self):
        import cv2
        rot = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(self.rotate)
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
                if rot is not None:
                    frame = cv2.rotate(frame, rot)
                with self._lock:
                    self._frame, self._stamp = frame, now
                    self._seq += 1
                self.shape = frame.shape
                count += 1
                if now - t0 >= 2.0:
                    self.fps, count, t0 = count / (now - t0), 0, now
            cap.release()
            self._stop.wait(1.0)
