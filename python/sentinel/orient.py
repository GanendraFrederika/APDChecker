"""Automatic camera orientation from people in view.

The sensor sits in the tube at an unknown multiple of 90 degrees (it was re-mounted
several times). A standing person is the best level: head above shoulders above hips.
Every few seconds while somebody is visible we score the frame in all four rotations
with the pose model and vote. Only a clear, repeated winner changes the rotation, so
a single odd pose (bending down, lying) never flips the picture.
"""
from collections import Counter


def upright_score(kps_list):
    """Sum over people of (+/-) confident keypoints: + if head above shoulders above hips."""
    total, people = 0.0, 0
    for k in kps_list:
        conf, xy = k.conf, k.xy
        vis = [c > 0.45 for c in conf]
        head = [xy[i][1] for i in range(0, 5) if vis[i]]
        sh = [xy[i][1] for i in (5, 6) if vis[i]]
        hip = [xy[i][1] for i in (11, 12) if vis[i]]
        if not head or not sh:
            continue
        people += 1
        hy, sy = sum(head) / len(head), sum(sh) / len(sh)
        ok = hy < sy and (not hip or sy < sum(hip) / len(hip))
        total += (1.0 if ok else -1.0) * sum(vis)
    return total, people


class AutoOrient:
    """Votes for the rotation (relative to the current one) that makes people upright."""

    def __init__(self, interval=4.0, votes_needed=3, min_margin=6.0):
        self.interval = interval
        self.votes_needed = votes_needed
        self.min_margin = min_margin
        self.last = -1e9
        self.votes = Counter()
        self.history = []
        self.confirmed = 0               # times the current rotation won clearly

    def due(self, now):
        # Once the rotation is confirmed a few times, re-check only every 30 s (4 extra
        # pose inferences per check cost CPU that tracking needs).
        return now - self.last >= (self.interval if self.confirmed < 3 else 30.0)

    def observe(self, now, scores):
        """scores: {extra_rotation: (score, people)} for 0/90/180/270 applied ON TOP of
        the current rotation. Returns the extra rotation to apply, or None."""
        self.last = now
        best = max(scores, key=lambda r: scores[r][0])
        ranked = sorted((s for s, _ in scores.values()), reverse=True)
        margin = ranked[0] - ranked[1]
        if scores[best][1] == 0 or scores[best][0] <= 0 or margin < self.min_margin:
            return None
        self.votes[best] += 1
        self.history.append((round(now, 1), best, round(margin, 1)))
        del self.history[:-10]
        if best == 0:
            self.votes.clear()            # current rotation confirmed
            self.confirmed += 1
            return None
        if self.votes[best] >= self.votes_needed:
            self.votes.clear()
            self.confirmed = 0
            return best
        return None
