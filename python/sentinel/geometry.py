"""Pixel <-> servo-angle mapping (small-angle pinhole model).

A pixel offset from the image centre maps to an angle offset through the lens
field of view. Signs encode the rig: on this build a LARGER pan angle turns the
camera LEFT (pan_sign=-1: an object right of centre needs a smaller pan angle),
and a LARGER tilt angle looks UP (tilt_sign=+1: an object below centre needs a
smaller tilt angle). `sentinel_calibrate` can measure fov/signs on the real rig.
"""
from dataclasses import dataclass
import math


@dataclass
class CameraModel:
    hfov_deg: float = 88.0          # SC3336 M12 lens on Luckfox kit (approx.)
    vfov_deg: float = 52.0
    pan_sign: int = -1
    tilt_sign: int = 1

    def offset_dd(self, px, py, width, height):
        """Angle offset (dd) of pixel (px,py) from the optical centre."""
        fx = (width / 2) / math.tan(math.radians(self.hfov_deg / 2))
        fy = (height / 2) / math.tan(math.radians(self.vfov_deg / 2))
        ax = math.degrees(math.atan((px - width / 2) / fx))    # + = right of centre
        ay = math.degrees(math.atan((py - height / 2) / fy))   # + = below centre
        # pan_sign=-1: turning right means a SMALLER pan angle. Below centre: look down.
        return self.pan_sign * ax * 10, -self.tilt_sign * ay * 10

    def to_angles(self, px, py, width, height, pan, tilt):
        """Servo angles (dd) that would centre pixel (px,py), given the pose at capture."""
        dx, dy = self.offset_dd(px, py, width, height)
        return pan + dx, tilt + dy

    def box_to_angles(self, box, width, height, pan, tilt):
        """Angle-space box (pan_left, tilt_top, pan_right, tilt_bottom)."""
        p1, t1 = self.to_angles(box[0], box[1], width, height, pan, tilt)
        p2, t2 = self.to_angles(box[2], box[3], width, height, pan, tilt)
        return (min(p1, p2), max(t1, t2), max(p1, p2), min(t1, t2))

    def to_pixel(self, a_pan, a_tilt, width, height, pan, tilt):
        """Inverse: where angle (a_pan,a_tilt) appears in a frame taken at (pan,tilt)."""
        fx = (width / 2) / math.tan(math.radians(self.hfov_deg / 2))
        fy = (height / 2) / math.tan(math.radians(self.vfov_deg / 2))
        ax = (a_pan - pan) / 10 / self.pan_sign
        ay = -(a_tilt - tilt) / 10 / self.tilt_sign
        return width / 2 + fx * math.tan(math.radians(ax)), height / 2 + fy * math.tan(math.radians(ay))
