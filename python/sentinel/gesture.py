"""Hand gestures for the person-lock robot (HOST CPU, MediaPipe Gesture Recognizer).

Recognised per hand: Thumb_Up, Open_Palm (greeting / 5 fingers), plus a glove check.
Each hand is assigned to the person whose wrist keypoint is closest, so in a group
the robot answers the right person.

Glove check: the PPE model's glove/no_glove boxes over the hand win when present;
otherwise skin colour on the palm area decides (bare skin -> no glove). Like the
vest, this colour rule is a heuristic and is reported as such.
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models/gesture_recognizer.task"


@dataclass(frozen=True)
class Hand:
    gesture: str            # Thumb_Up / Open_Palm / ...
    score: float
    box: tuple              # pixel box of the hand
    wrist: tuple            # pixel (x, y)
    glove: str              # PRESENT / ABSENT / UNKNOWN
    glove_method: str


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

    def hands(self, frame, ppe=()):
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
            glove, method = glove_state(frame, box, ppe)
            out.append(Hand(name, float(top.score) if top else 0.0, box, (xs[0], ys[0]), glove, method))
        return out


def _overlap(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def glove_state(frame, box, ppe=()):
    pos = [d.conf for d in ppe if d.label == "glove" and _overlap(box, d.box) > 0.2]
    neg = [d.conf for d in ppe if d.label == "no_glove" and _overlap(box, d.box) > 0.2]
    if pos and not neg:
        return "PRESENT", "MODEL"
    if neg and not pos:
        return "ABSENT", "MODEL"
    import cv2
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = (int(max(0, box[0])), int(max(0, box[1])), int(min(w, box[2])), int(min(h, box[3])))
    if x2 - x1 < 12 or y2 - y1 < 12:
        return "UNKNOWN", "SMALL"
    ycc = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2YCrCb)
    skin = cv2.inRange(ycc, (40, 135, 85), (255, 175, 135))
    share = float(np.count_nonzero(skin)) / skin.size
    if share >= 0.35:
        return "ABSENT", "COLOR"
    if share <= 0.10:
        return "PRESENT", "COLOR"
    return "UNKNOWN", "COLOR"


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
