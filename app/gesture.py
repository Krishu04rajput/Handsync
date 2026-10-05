"""Hand geometry -> features -> gestures (OPEN / PINCH / FIST / NEUTRAL)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

import config

# MediaPipe hand landmark indices
WRIST = 0
THUMB_IP, THUMB_TIP = 3, 4
INDEX_MCP, INDEX_TIP = 5, 8
MIDDLE_MCP, MIDDLE_TIP = 9, 12
RING_MCP, RING_TIP = 13, 16
PINKY_MCP, PINKY_TIP = 17, 20
PALM_POINTS = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)

OPEN, PINCH, FIST, NEUTRAL = "OPEN", "PINCH", "FIST", "NEUTRAL"

_FINGERS = ((INDEX_TIP, INDEX_MCP), (MIDDLE_TIP, MIDDLE_MCP), (RING_TIP, RING_MCP), (PINKY_TIP, PINKY_MCP))
_FINGER_EXTENDED_RATIO = 1.5


@dataclass
class HandFeatures:
    palm_x: float        # 0..1, in "mirror" control coordinates (moving hand right => larger)
    palm_y: float        # 0..1, top of image = 0
    tilt_deg: float      # hand roll: 0 = fingers up, + = fingers lean right
    pinch_ratio: float   # thumb-index distance / palm size
    openness: float      # mean (tip-wrist)/(mcp-wrist) of middle, ring, pinky
    fingers: tuple[bool, bool, bool, bool, bool]  # thumb, index, middle, ring, pinky extended


@dataclass
class HandObservation:
    arm: str             # "left" / "right" (robot arm this hand controls)
    label: str           # MediaPipe handedness label
    features: HandFeatures
    gesture: str         # debounced gesture


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def analyze_hand(landmarks: np.ndarray, mirror: bool = True, aspect: float = 4 / 3) -> HandFeatures:
    """Compute rotation-invariant features from 21 normalised landmarks (x, y, z).

    Distances are measured with x scaled by the image aspect ratio so they are
    real-looking distances, not stretched normalised ones. Everything is divided by
    palm size (wrist->middle MCP) so it works at any distance from the camera.
    """
    lm = np.asarray(landmarks, dtype=float)
    if lm.ndim != 2 or lm.shape[0] < 21 or lm.shape[1] < 2:
        raise ValueError("expected 21 landmarks with at least x,y")
    xy = lm[:, :2].copy()
    xy[:, 0] *= aspect

    palm_size = max(_dist(xy[WRIST], xy[MIDDLE_MCP]), 1e-6)
    pinch_ratio = _dist(xy[THUMB_TIP], xy[INDEX_TIP]) / palm_size

    ratios = [_dist(xy[tip], xy[WRIST]) / max(_dist(xy[mcp], xy[WRIST]), 1e-6) for tip, mcp in _FINGERS]
    openness = float(np.mean(ratios[1:]))
    thumb_extended = _dist(xy[THUMB_TIP], xy[PINKY_MCP]) > _dist(xy[THUMB_IP], xy[PINKY_MCP])
    fingers = (thumb_extended,) + tuple(r >= _FINGER_EXTENDED_RATIO for r in ratios)

    # Palm centre is steadier than the wrist alone (average of wrist + 4 knuckles)
    cx, cy = lm[list(PALM_POINTS), :2].mean(axis=0)
    palm_x = float(cx if mirror else 1.0 - cx)

    sign = 1.0 if mirror else -1.0
    dx = (lm[MIDDLE_MCP, 0] - lm[WRIST, 0]) * aspect * sign
    dy = lm[MIDDLE_MCP, 1] - lm[WRIST, 1]
    tilt = math.degrees(math.atan2(dx, -dy))   # image y points down, so "up" is -dy

    return HandFeatures(palm_x, float(cy), tilt, float(pinch_ratio), openness, fingers)  # type: ignore[arg-type]


def classify_gesture(f: HandFeatures, previous: str = NEUTRAL) -> str:
    """Raw (un-debounced) gesture. Order matters: FIST, then PINCH, then OPEN."""
    if f.openness < config.GESTURE_FIST_MAX_OPENNESS:
        return FIST
    pinch_limit = config.PINCH_RELEASE_RATIO if previous == PINCH else config.PINCH_CLOSE_RATIO
    if f.pinch_ratio < pinch_limit:
        return PINCH
    if f.openness >= config.GESTURE_OPEN_MIN_OPENNESS:
        return OPEN
    return NEUTRAL


class GestureDebouncer:
    """A new gesture must be seen for N consecutive frames before it becomes the stable one."""

    def __init__(self, frames: int = config.GESTURE_DEBOUNCE_FRAMES):
        self.frames = max(1, frames)
        self.stable = NEUTRAL
        self._candidate = NEUTRAL
        self._count = 0

    def update(self, raw: str) -> str:
        if raw == self.stable:
            self._candidate, self._count = raw, 0
        elif raw == self._candidate:
            self._count += 1
            if self._count >= self.frames:
                self.stable, self._count = raw, 0
        else:
            self._candidate, self._count = raw, 1
            if self.frames <= 1:
                self.stable, self._count = raw, 0
        return self.stable

    def reset(self) -> None:
        self.stable, self._candidate, self._count = NEUTRAL, NEUTRAL, 0


class GripperLogic:
    """OPEN gesture -> open, PINCH -> closed, FIST / NEUTRAL -> hold current state."""

    def __init__(self, start_open: bool = True):
        self.is_open = start_open

    def update(self, gesture: Optional[str]) -> bool:
        if gesture == OPEN:
            self.is_open = True
        elif gesture == PINCH:
            self.is_open = False
        return self.is_open
