"""Hand gestures for the person-lock robot (HOST CPU, MediaPipe Gesture Recognizer).

Recognised per hand: Thumb_Up, Open_Palm (greeting / 5 fingers).
Each hand is assigned to the person whose wrist keypoint is closest, so in a group
the robot answers the right person.
"""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models/gesture_recognizer.task"


@dataclass(frozen=True)
class Hand:
    gesture: str            # Thumb_Up / Open_Palm / ...
    score: float
    box: tuple              # pixel box of the hand
    wrist: tuple            # pixel (x, y)


class GestureReader:
    def __init__(self, model=MODEL, max_hands=4, min_score=0.6):
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        self._mp = mp
        opts = vision.GestureRecognizerOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.IMAGE, num_hands=max_hands,
            min_hand_detection_confidence=0.5, min_hand_presence_confidence=0.5)
        self._rec = vision.GestureRecognizer.create_from_options(opts)
        self.min_score = min_score

    def close(self):
        try:
            self._rec.close()
        except Exception:
            pass

    def hands(self, frame):
        import cv2
        h, w = frame.shape[:2]
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                               data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        res = self._rec.recognize(image)
        out = []
        for lms, gestures in zip(res.hand_landmarks, res.gestures):
            xs = [p.x * w for p in lms]
            ys = [p.y * h for p in lms]
            box = (min(xs), min(ys), max(xs), max(ys))
            top = gestures[0] if gestures else None
            name = top.category_name if top is not None and top.score >= self.min_score else "None"
            out.append(Hand(name, float(top.score) if top else 0.0, box, (xs[0], ys[0])))
        return out


def owner(hand, tracks, max_dist_frac=0.35):
    """Track whose wrist (or box) is nearest to the hand; None if ambiguous/far."""
    best, best_d = None, None
    for t in tracks:
        x1, y1, x2, y2 = t.pixel_box
        pts = []
        if t.kps is not None:
            for name in ("l_wrist", "r_wrist"):
                if t.kps.visible(name, 0.3):
                    pts.append(t.kps.point(name))
        if not pts:
            pts = [((x1 + x2) / 2, (y1 + y2) / 2)]
        d = min(((p[0] - hand.wrist[0]) ** 2 + (p[1] - hand.wrist[1]) ** 2) ** 0.5 for p in pts)
        limit = max_dist_frac * max(x2 - x1, y2 - y1)
        inside = x1 - 0.2 * (x2 - x1) <= hand.wrist[0] <= x2 + 0.2 * (x2 - x1) and y1 <= hand.wrist[1] <= y2 + 0.1 * (y2 - y1)
        if (d <= limit or inside) and (best_d is None or d < best_d):
            best, best_d = t, d
    return best
