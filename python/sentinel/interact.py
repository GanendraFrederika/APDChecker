"""Gesture interaction rules (owner's spec, 25-10-2026).

While the camera looks at a person:
  * thumbs-up WITH gloves    -> nod "yes" (cooldown 5 s per nod) + friendly greeting
  * thumbs-up WITHOUT gloves -> shake "no" ONCE, then the alarm starts for that person
  * open palm (5 fingers / waving) -> greeting voice + happy bob, if PPE is complete
    or still being checked (a confirmed violator gets no greeting)
Debug toggle `assume_gloves`: treat every hand as gloved so thumbs-up can be tested
without wearing gloves.
A gesture must be seen on 2 consecutive analysed frames (one flicker is ignored).
"""
from dataclasses import dataclass, field

NOD_COOLDOWN = 5.0
GREET_COOLDOWN = 8.0
CONFIRM_FRAMES = 2


@dataclass
class PersonState:
    gesture: str = "None"
    streak: int = 0
    last_nod: float = -1e9
    last_greet: float = -1e9
    shook: bool = False            # "no" already shown to this person
    glove_alarm: bool = False      # alarm because of a bare-hand thumbs-up


@dataclass
class InteractConfig:
    assume_gloves: bool = False


class Interaction:
    def __init__(self, cfg=None):
        self.cfg = cfg or InteractConfig()
        self.people: dict[int, PersonState] = {}
        self.fx = "-"
        self.fx_id = 0
        self.events = []

    def _fire(self, fx, note):
        self.fx = fx
        self.fx_id = (self.fx_id + 1) % 256
        self.events.append(note)

    def update(self, now, tracks, hands_by_track, voice=None):
        """hands_by_track: {track_id: [Hand, ...]}. Returns the fx request for this frame."""
        self.events = []
        live = {t.tid for t in tracks}
        self.people = {tid: st for tid, st in self.people.items() if tid in live}
        for t in tracks:
            st = self.people.setdefault(t.tid, PersonState())
            hands = hands_by_track.get(t.tid, [])
            gesture = "None"
            gloved = False
            for hnd in hands:
                if hnd.gesture in ("Thumb_Up", "Open_Palm"):
                    gesture = hnd.gesture
                    gloved = self.cfg.assume_gloves or hnd.glove == "PRESENT"
                    if gesture == "Thumb_Up":
                        break
            st.streak = st.streak + 1 if gesture == st.gesture and gesture != "None" else (1 if gesture != "None" else 0)
            st.gesture = gesture
            if st.streak != CONFIRM_FRAMES:        # act once, when the gesture is confirmed
                continue
            if gesture == "Thumb_Up":
                if gloved:
                    if now - st.last_nod >= NOD_COOLDOWN:
                        st.last_nod = now
                        self._fire("N", f"#{t.tid} jempol + sarung tangan -> angguk")
                        if voice is not None:
                            voice.greet()
                elif not st.shook:
                    st.shook = True
                    st.glove_alarm = True
                    self._fire("H", f"#{t.tid} jempol TANPA sarung tangan -> geleng + alarm")
                    if voice is not None:
                        voice.say("apd_kurang", force=True)
            elif gesture == "Open_Palm":
                if t.state() != "VIOLATION" and now - st.last_greet >= GREET_COOLDOWN:
                    st.last_greet = now
                    self._fire("W", f"#{t.tid} melambai -> sapa")
                    if voice is not None:
                        voice.greet()
        return self.fx, self.fx_id

    def glove_alarm(self, tid):
        st = self.people.get(tid)
        return bool(st and st.glove_alarm)
