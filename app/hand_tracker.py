"""MediaPipe Hand Landmarker (Tasks API) wrapper.

Uses ONLY the modern Tasks API:
    mediapipe.tasks.python.BaseOptions
    mediapipe.tasks.python.vision.HandLandmarker / HandLandmarkerOptions / RunningMode
The old `mp.solutions.hands` API is NOT used anywhere.
"""
from __future__ import annotations

import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

import config
from app.logger import get_logger

log = get_logger(__name__)

# Hand skeleton (pairs of landmark indices) used for drawing - same as MediaPipe's standard hand graph.
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

MODEL_HELP = (
    "How to get the model:\n"
    "  1) Click 'Download now' in this window (needs internet), or run:  python download_model.py\n"
    "  2) Or download it manually from:\n     " + config.MODEL_URL + "\n"
    "     and save it as:\n     " + str(config.MODEL_PATH)
)


class HandTrackerError(Exception):
    """Human-readable tracker problem (model missing, MediaPipe failed, ...)."""


@dataclass
class RawHand:
    label: str                 # "Left" / "Right" as reported by MediaPipe
    score: float
    landmarks: np.ndarray      # shape (21, 3), normalised x, y, z


# ------------------------------------------------------------------ model file handling
def model_status(path: Path = config.MODEL_PATH) -> tuple[bool, str]:
    """Return (ok, message) describing the hand-landmarker model file."""
    if not path.exists():
        return False, "Hand Landmarker model not found.\n\nExpected file:\n" + str(path) + "\n\n" + MODEL_HELP
    size = path.stat().st_size
    if size < config.MODEL_MIN_BYTES:
        return False, (f"Hand Landmarker model looks invalid (only {size} bytes).\n"
                       "Delete it and download it again.\n\n" + MODEL_HELP)
    return True, "Model OK"


def download_model(path: Path = config.MODEL_PATH, url: str = config.MODEL_URL) -> None:
    """Download hand_landmarker.task. Raises HandTrackerError with a clear message on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading hand landmarker model from %s", url)
    tmp_name = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "HANDSYNC"})
        with urllib.request.urlopen(request, timeout=30) as response:
            with tempfile.NamedTemporaryFile(delete=False, dir=str(path.parent), suffix=".part") as tmp:
                tmp_name = tmp.name
                while True:
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    tmp.write(chunk)
        if os.path.getsize(tmp_name) < config.MODEL_MIN_BYTES:
            raise HandTrackerError("Downloaded file is too small - the download was incomplete.")
        os.replace(tmp_name, path)
        tmp_name = None
        log.info("Model saved to %s", path)
    except HandTrackerError:
        raise
    except Exception as exc:  # network errors, DNS, SSL, disk
        log.error("Model download failed: %s", exc)
        raise HandTrackerError(f"Could not download the model ({exc}).\n\n" + MODEL_HELP) from exc
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


# ------------------------------------------------------------------ tracker
class HandTracker:
    """Runs MediaPipe HandLandmarker in VIDEO mode (needs strictly increasing timestamps)."""

    def __init__(self, model_path: Path = config.MODEL_PATH):
        ok, message = model_status(model_path)
        if not ok:
            raise HandTrackerError(message)
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except ImportError as exc:
            raise HandTrackerError(
                "MediaPipe is not installed (or is not compatible with this Python version).\n"
                "Run:  python -m pip install -r requirements.txt\n"
                "Recommended: Python 3.12 (see README)."
            ) from exc
        self._mp = mp
        try:
            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=config.MAX_HANDS,
                min_hand_detection_confidence=config.MIN_HAND_DETECTION_CONFIDENCE,
                min_hand_presence_confidence=config.MIN_HAND_PRESENCE_CONFIDENCE,
                min_tracking_confidence=config.MIN_TRACKING_CONFIDENCE,
            )
            self._landmarker = vision.HandLandmarker.create_from_options(options)
        except Exception as exc:
            log.exception("MediaPipe initialisation failed")
            raise HandTrackerError(
                f"MediaPipe could not start the Hand Landmarker ({exc}).\n"
                "The model file may be damaged - delete models/hand_landmarker.task and download it again."
            ) from exc
        self._last_ts = -1
        log.info("MediaPipe HandLandmarker initialised (mediapipe %s)", getattr(mp, "__version__", "?"))

    def detect(self, rgb_frame: np.ndarray, timestamp_ms: int) -> list[RawHand]:
        """Detect hands in an RGB uint8 frame."""
        timestamp_ms = max(int(timestamp_ms), self._last_ts + 1)   # must strictly increase
        self._last_ts = timestamp_ms
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb_frame))
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        hands: list[RawHand] = []
        for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
            points = np.array([[p.x, p.y, p.z] for p in landmarks], dtype=float)
            category = handedness[0]
            hands.append(RawHand(category.category_name, float(category.score), points))
        return hands

    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:  # closing must never raise
            pass


# ------------------------------------------------------------------ left/right assignment
def user_side(label: str, mirrored_input: bool) -> str:
    """Which physical hand is this?

    MediaPipe assumes a mirrored (selfie) image. If we feed it a mirrored frame the label is the
    user's real hand; if we feed a non-mirrored frame the label is reversed.
    """
    side = label.strip().lower()
    if mirrored_input:
        return side
    return "right" if side == "left" else "left"


def assign_arms(hands: list[RawHand], mirrored_input: bool, swap: bool = False) -> dict[str, RawHand]:
    """Map detected hands to robot arms ('left' / 'right'). Left hand -> left arm unless swapped."""
    assigned: dict[str, RawHand] = {}
    if not hands:
        return assigned
    sides: list[Optional[str]] = [user_side(h.label, mirrored_input) for h in hands]
    if len(hands) >= 2 and sides[0] == sides[1]:
        # Both hands got the same label (happens with noisy detection): decide by position instead.
        # Mirrored view: user's left hand appears on the left (small x). Raw view: reversed.
        two = sorted(hands[:2], key=lambda h: float(h.landmarks[0, 0]))
        left_hand, right_hand = (two[0], two[1]) if mirrored_input else (two[1], two[0])
        pairs = [("left", left_hand), ("right", right_hand)]
    else:
        pairs = []
        for hand, side in sorted(zip(hands, sides), key=lambda t: -t[0].score):
            if side in ("left", "right") and side not in [p[0] for p in pairs]:
                pairs.append((side, hand))
    for side, hand in pairs:
        arm = ("right" if side == "left" else "left") if swap else side
        assigned[arm] = hand
    return assigned
