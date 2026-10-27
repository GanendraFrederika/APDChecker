"""Shared immutable data types. No I/O. Pixel boxes are (x1, y1, x2, y2) in the
(rotated) analysis frame; keypoints follow the 17-point COCO order."""
from dataclasses import dataclass

ITEMS = ("helmet", "vest", "shoes")  # wire order H, V, S (+ "-" reserved 4th char, SLP/1.1)
MODES = frozenset("IPATGVSF")
KP = dict(nose=0, l_eye=1, r_eye=2, l_ear=3, r_ear=4, l_shoulder=5, r_shoulder=6,
          l_elbow=7, r_elbow=8, l_wrist=9, r_wrist=10, l_hip=11, r_hip=12,
          l_knee=13, r_knee=14, l_ankle=15, r_ankle=16)


@dataclass(frozen=True)
class Keypoints:
    xy: tuple          # 17 x (x, y) pixels
    conf: tuple        # 17 x confidence 0..1

    def visible(self, name, threshold=0.5):
        return self.conf[KP[name]] >= threshold

    def point(self, name):
        return self.xy[KP[name]]


@dataclass(frozen=True)
class PersonDet:
    box: tuple
    conf: float
    kps: Keypoints | None = None

    @property
    def center(self):
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2, (y1 + y2) / 2

    @property
    def height(self):
        return self.box[3] - self.box[1]


@dataclass(frozen=True)
class PpeDet:
    label: str         # normalized: helmet, no_helmet, shoes, no_shoes, vest, no_vest, ...
    conf: float
    box: tuple


@dataclass(frozen=True)
class Region:
    box: tuple | None          # pixel box of the body region (None if unknown)
    visibility: str            # OBSERVABLE | NOT_VISIBLE | UNKNOWN
    reason: str


@dataclass(frozen=True)
class Command:
    """One SLP/1.1 S-frame payload (angles are servo deci-degrees 0..1800)."""
    mode: str
    pan: int
    tilt: int
    spd: int
    items: str = "---"            # helmet, vest, shoes
    alarm: bool = False
    ppl: int = 0
    viol: int = 0
    trk: int = 0
    fx: str = "-"                 # animation request: - N(od) H(ead shake) C(urious) W(ave)
    fx_id: int = 0                # change it to trigger the animation again
    vox: bool = False             # brain allows sound (siren + chimes)
