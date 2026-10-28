"""Person + PPE perception (HOST CPU). Pose keypoints decide WHICH body region is
visible, so a hidden region is UNKNOWN, never "missing".

Models (local files only, no downloads):
  models/yolo11n-pose.pt     person boxes + 17 COCO keypoints
  models/ppe_helmet_vest.pt  hardhat / no-hardhat / safety vest / no-safety vest
                             (YOLOv8n, Hansung-Cho, MIT). construction-ppe test set:
                             helmet AP50 0.78, vest AP50 0.74, ~100 ms @320 on this PC
  models/ppe_boots.pt        boots / no-boots (YOLOv8s, SafeSight, Apache-2.0),
                             shoes AP50 0.52; run every few frames (slow, feet move little)
Colour checks remain only as a fallback when a model sees nothing (method=COLOR).
Evaluation: scripts/eval_ppe.py, results in docs/sentinel/ppe_model_eval.md.
"""
import os
from pathlib import Path
import time

import numpy as np

from .types import Keypoints, PersonDet, PpeDet, Region

ROOT = Path(__file__).resolve().parents[2]
KP_CONF = 0.45
PROJECT_MODEL = ROOT / "models/ppe_project.pt"     # fine-tuned on our workshop (train_ppe.py)
HELMET_VEST_MODEL = ROOT / "models/ppe_helmet_vest.pt"
BOOTS_MODEL = ROOT / "models/ppe_boots.pt"
LEGACY_MODEL = ROOT / "models/ppe_yolov8n.pt"

# Every model names classes its own way; map them to the labels evidence() uses.
LABELS = {
    "hardhat": "helmet", "hard_hat": "helmet", "helmet": "helmet",
    "no_hardhat": "no_helmet", "no_helmet": "no_helmet",
    "safety_vest": "vest", "vest": "vest",
    "no_safety_vest": "no_vest", "no_vest": "no_vest",
    "boots": "shoes", "shoes": "shoes",
    "no_boots": "no_shoes", "no_shoes": "no_shoes",
}


def _norm(label):
    return label.lower().strip().replace("-", "_").replace(" ", "_")


class Perception:
    def __init__(self, pose_path=None, imgsz=416, ppe_imgsz=320, boots_imgsz=256, boots_every=1.0,
                 person_conf=0.4, ppe_conf=0.5, boots_conf=0.45):
        os.environ.setdefault("YOLO_OFFLINE", "1")
        os.environ.setdefault("YOLO_AUTOINSTALL", "false")
        import torch
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 2)))
        from ultralytics import YOLO
        self.pose = YOLO(str(pose_path or ROOT / "models/yolo11n-pose.pt"))
        if self.pose.task != "pose":
            raise ValueError("Pose model required")
        main = next(p for p in (PROJECT_MODEL, HELMET_VEST_MODEL, LEGACY_MODEL) if p.exists())
        self.ppe = YOLO(str(main))
        own_shoes = any(LABELS.get(_norm(n)) == "shoes" for n in self.ppe.names.values())
        # A project model that knows shoes itself does not need the slow boots model.
        self.boots = YOLO(str(BOOTS_MODEL)) if BOOTS_MODEL.exists() and not own_shoes else None
        self.ppe_names = {i: LABELS.get(_norm(n)) for i, n in self.ppe.names.items()}
        self.boots_names = ({i: LABELS.get(_norm(n)) for i, n in self.boots.names.items()}
                            if self.boots is not None else {})
        if self.boots is not None:          # the boots model is only trusted for feet
            self.boots_names = {i: n if n in ("shoes", "no_shoes") else None for i, n in self.boots_names.items()}
        self.models = [main.name] + ([BOOTS_MODEL.name] if self.boots is not None else [])
        self.imgsz, self.ppe_imgsz, self.boots_imgsz = imgsz, ppe_imgsz, boots_imgsz
        self.boots_every = boots_every
        self.person_conf, self.ppe_conf, self.boots_conf = person_conf, ppe_conf, boots_conf
        self._boots_at, self._boots_cache = -1e9, []

    def people(self, frame):
        r = self.pose.predict(frame, imgsz=self.imgsz, conf=self.person_conf, device="cpu",
                              verbose=False, max_det=12)[0]
        out = []
        if r.boxes is None or not len(r.boxes):
            return out
        boxes = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        kxy = r.keypoints.xy.cpu().numpy() if r.keypoints is not None else None
        kcf = r.keypoints.conf.cpu().numpy() if r.keypoints is not None and r.keypoints.conf is not None else None
        for i, b in enumerate(boxes):
            kps = None
            if kxy is not None and kcf is not None:
                kps = Keypoints(tuple(map(tuple, kxy[i].tolist())), tuple(kcf[i].tolist()))
            out.append(PersonDet(tuple(float(v) for v in b), float(confs[i]), kps))
        return out

    @staticmethod
    def _detect(model, names, crop, x1, y1, imgsz, conf):
        r = model.predict(crop, imgsz=imgsz, conf=conf, device="cpu", verbose=False, max_det=64)[0]
        out = []
        if r.boxes is None:
            return out
        for b, c, k in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(),
                           r.boxes.cls.cpu().numpy()):
            label = names.get(int(k))
            if label:
                out.append(PpeDet(label, float(c), (b[0] + x1, b[1] + y1, b[2] + x1, b[3] + y1)))
        return out

    def equipment(self, frame, people):
        """PPE on the union of the person crops (more pixels per item than full frame)."""
        if not people:
            return []
        h, w = frame.shape[:2]
        x1 = max(0, int(min(p.box[0] for p in people) - 0.08 * w))
        y1 = max(0, int(min(p.box[1] for p in people) - 0.08 * h))
        x2 = min(w, int(max(p.box[2] for p in people) + 0.08 * w))
        y2 = min(h, int(max(p.box[3] for p in people) + 0.05 * h))
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return []
        out = self._detect(self.ppe, self.ppe_names, crop, x1, y1, self.ppe_imgsz, self.ppe_conf)
        if self.boots is not None:
            now = time.monotonic()
            if now - self._boots_at >= self.boots_every:
                # Feet only: the lower 45 % of the people box (more pixels per shoe).
                fy1 = max(y1, int(y2 - 0.45 * (y2 - y1)))
                feet = frame[fy1:y2, x1:x2]
                self._boots_cache = (self._detect(self.boots, self.boots_names, feet, x1, fy1,
                                                  self.boots_imgsz, self.boots_conf) if feet.size else [])
                self._boots_at = now
            out += self._boots_cache
        return out


# ---------------------------------------------------------------- body regions

def _pt(k, name):
    return k.point(name) if k.visible(name, KP_CONF) else None


def regions(person: PersonDet, frame_shape):
    """Pixel boxes for head / torso / feet and whether each is OBSERVABLE."""
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = person.box
    bw, bh = x2 - x1, y2 - y1
    k = person.kps
    edge = 4
    out = {}
    if k is None:
        unknown = Region(None, "UNKNOWN", "NO_KEYPOINTS")
        return {"helmet": unknown, "vest": unknown, "shoes": unknown}

    # Head: any facial/ear keypoint; helmet box extends upward from it.
    head_pts = [p for p in (_pt(k, n) for n in ("nose", "l_eye", "r_eye", "l_ear", "r_ear")) if p]
    shoulders = [p for p in (_pt(k, "l_shoulder"), _pt(k, "r_shoulder")) if p]
    if head_pts:
        hx = sum(p[0] for p in head_pts) / len(head_pts)
        hy = min(p[1] for p in head_pts)
        size = max(bw * 0.45, 24.0)
        box = (hx - size / 2, hy - size * 0.9, hx + size / 2, hy + size * 0.5)
        # The person box touching the top edge is fine as long as the crown band above
        # the eyes is still inside the picture (a hard hat sits right there).
        # Head size from the face keypoints (eye/ear spread), not from the body box:
        # a close-up person box is huge while the head stays small.
        eyes = [p for p in (_pt(k, "l_eye"), _pt(k, "r_eye")) if p]
        eye_y = min(p[1] for p in eyes) if eyes else hy
        spread = max(p[0] for p in head_pts) - min(p[0] for p in head_pts)
        crown_in_view = eye_y - 0.6 * max(spread, 12.0) > 0
        vis = "OBSERVABLE" if (y1 > edge or crown_in_view) else "UNKNOWN"
        out["helmet"] = Region(box, vis, "HEAD_KEYPOINTS" if vis == "OBSERVABLE" else "HEAD_AT_FRAME_EDGE")
    else:
        out["helmet"] = Region(None, "NOT_VISIBLE", "HEAD_NOT_VISIBLE")

    # Torso: both shoulders plus at least one hip.
    hips = [p for p in (_pt(k, "l_hip"), _pt(k, "r_hip")) if p]
    if len(shoulders) == 2 and hips:
        xs = [p[0] for p in shoulders + hips]
        ys = [p[1] for p in shoulders + hips]
        pad = 0.08 * (max(xs) - min(xs) + 1)
        box = (min(xs) - pad, min(ys), max(xs) + pad, max(ys))
        out["vest"] = Region(box, "OBSERVABLE", "TORSO_KEYPOINTS")
    else:
        out["vest"] = Region(None, "NOT_VISIBLE", "TORSO_NOT_VISIBLE")

    # Feet: ankles visible and the person box does not touch the bottom edge.
    ankles = [p for p in (_pt(k, "l_ankle"), _pt(k, "r_ankle")) if p]
    if ankles and y2 < h - edge:
        ax = [p[0] for p in ankles]
        ay = max(p[1] for p in ankles)
        size = max(bw * 0.35, 20.0)
        box = (min(ax) - size, ay - size * 0.6, max(ax) + size, min(h, ay + size * 0.7))
        out["shoes"] = Region(box, "OBSERVABLE", "ANKLE_KEYPOINTS")
    elif ankles:
        out["shoes"] = Region(None, "UNKNOWN", "FEET_AT_FRAME_EDGE")
    else:
        out["shoes"] = Region(None, "NOT_VISIBLE", "FEET_NOT_VISIBLE")
    return out


def _overlap(box, region_box):
    """Fraction of `box` inside `region_box`."""
    ix = max(0.0, min(box[2], region_box[2]) - max(box[0], region_box[0]))
    iy = max(0.0, min(box[3], region_box[3]) - max(box[1], region_box[1]))
    area = max(1e-6, (box[2] - box[0]) * (box[3] - box[1]))
    return ix * iy / area


def vest_color(frame, region_box):
    """Hi-vis check: share of fluorescent yellow-green / orange pixels on the torso.
    Returns (state, score) with state PRESENT / ABSENT / UNKNOWN."""
    import cv2
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = (int(max(0, region_box[0])), int(max(0, region_box[1])),
                      int(min(w, region_box[2])), int(min(h, region_box[3])))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return "UNKNOWN", 0.0
    hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    v_mean = float(hsv[..., 2].mean())
    if v_mean < 45:
        return "UNKNOWN", 0.0                     # too dark to judge colour
    # Hi-vis = strongly saturated AND bright: lime/yellow, orange, red-orange.
    # Skin is orange-ish too but far less saturated, so the saturation floor matters.
    yellow = cv2.inRange(hsv, (22, 110, 120), (48, 255, 255))
    orange = cv2.inRange(hsv, (0, 165, 130), (20, 255, 255))
    redwrap = cv2.inRange(hsv, (168, 165, 130), (180, 255, 255))
    score = float(np.count_nonzero(yellow | orange | redwrap)) / yellow.size
    if score >= 0.15:
        return "PRESENT", score
    if score <= 0.04:
        return "ABSENT", score
    return "UNKNOWN", score


def helmet_color(frame, kps):
    """Crown band just above the eyes, between the ears (pose keypoints).
    Hard hat -> bright/saturated shell; bare head -> dark hair or skin.
    Returns (state, score) with state PRESENT / ABSENT / UNKNOWN."""
    import cv2
    pts = [kps.point(n) for n in ("l_eye", "r_eye", "l_ear", "r_ear", "nose") if kps.visible(n, KP_CONF)]
    eyes = [kps.point(n) for n in ("l_eye", "r_eye") if kps.visible(n, KP_CONF)]
    if len(pts) < 3 or not eyes:
        return "UNKNOWN", 0.0
    xs = [p[0] for p in pts]
    width = max(xs) - min(xs)
    if width < 10:
        return "UNKNOWN", 0.0
    eye_y = min(p[1] for p in eyes)
    cx = (max(xs) + min(xs)) / 2
    h, w = frame.shape[:2]
    x1, x2 = int(max(0, cx - 0.55 * width)), int(min(w, cx + 0.55 * width))
    y1, y2 = int(max(0, eye_y - 0.85 * width)), int(max(0, eye_y - 0.25 * width))
    if x2 - x1 < 8 or y2 - y1 < 6:
        return "UNKNOWN", 0.0
    roi = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    ycc = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
    n = float(roi.shape[0] * roi.shape[1])
    dark = np.count_nonzero(cv2.inRange(hsv, (0, 0, 0), (180, 255, 70))) / n
    skin = np.count_nonzero(cv2.inRange(ycc, (60, 135, 85), (255, 175, 135))) / n
    white = np.count_nonzero(cv2.inRange(hsv, (0, 0, 170), (180, 55, 255))) / n
    vivid = np.count_nonzero(cv2.inRange(hsv, (0, 120, 120), (180, 255, 255))) / n
    shell = white + vivid
    if dark >= 0.35 or skin >= 0.55:
        return "ABSENT", shell
    if shell >= 0.45 and dark <= 0.2:
        return "PRESENT", shell
    return "UNKNOWN", shell


def evidence(person, regs, ppe, frame):
    """Per-item raw evidence for ONE person this frame.
    Returns {item: (raw, confidence, method)} with raw PRESENT/ABSENT/UNKNOWN."""
    out = {}
    for item in ("helmet", "shoes"):
        reg = regs[item]
        if reg.visibility != "OBSERVABLE" or reg.box is None:
            out[item] = ("UNKNOWN", 0.0, reg.reason)
            continue
        pos = [d.conf for d in ppe if d.label == item and _overlap(d.box, reg.box) >= 0.35]
        neg = [d.conf for d in ppe if d.label == "no_" + item and _overlap(d.box, reg.box) >= 0.35]
        if pos and neg:
            out[item] = ("UNKNOWN", 0.0, "CONFLICT")
        elif pos:
            out[item] = ("PRESENT", max(pos), "MODEL")
        elif neg:
            out[item] = ("ABSENT", max(neg), "MODEL")
        elif item == "helmet" and person.kps is not None:
            state, score = helmet_color(frame, person.kps)   # model missed: colour fallback
            out[item] = (state, score, "COLOR")
        else:
            out[item] = ("UNKNOWN", 0.0, "NO_DETECTION")
    reg = regs["vest"]
    vest_pos = [d.conf for d in ppe if d.label == "vest" and reg.box and _overlap(d.box, reg.box) >= 0.3]
    vest_neg = [d.conf for d in ppe if d.label == "no_vest" and reg.box and _overlap(d.box, reg.box) >= 0.3]
    if reg.visibility != "OBSERVABLE" or reg.box is None:
        out["vest"] = ("UNKNOWN", 0.0, reg.reason)
    elif vest_pos or vest_neg:                     # a future model with a vest class wins
        out["vest"] = ("PRESENT", max(vest_pos), "MODEL") if vest_pos and not vest_neg else \
                      ("ABSENT", max(vest_neg), "MODEL") if vest_neg and not vest_pos else ("UNKNOWN", 0.0, "CONFLICT")
    else:
        state, score = vest_color(frame, reg.box)
        out["vest"] = (state, score, "COLOR")
    return out
