"""Camera + hand tracking worker thread (keeps the GUI responsive)."""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

import config
from app.gesture import (NEUTRAL, GestureDebouncer, HandObservation,
                         analyze_hand, classify_gesture)
from app.hand_tracker import HAND_CONNECTIONS, HandTracker, HandTrackerError, RawHand, assign_arms
from app.logger import get_logger

log = get_logger(__name__)

ARM_COLORS = {"left": (255, 200, 40), "right": (60, 220, 120)}   # BGR: cyan-blue / green


class CameraError(Exception):
    """Human-readable camera problem."""


@dataclass
class FrameResult:
    image: QImage
    observations: dict = field(default_factory=dict)   # arm -> HandObservation | None
    fps: float = 0.0
    hands_detected: int = 0


def open_camera(index: int) -> cv2.VideoCapture:
    """Open a webcam with the best Windows backend; raises CameraError with advice."""
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if sys.platform == "win32" else [cv2.CAP_ANY]
    for backend in backends:
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, config.CAMERA_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        if ok and frame is not None:
            h, w = frame.shape[:2]
            if (w, h) != (config.CAMERA_WIDTH, config.CAMERA_HEIGHT):
                log.warning("Camera %d does not support %dx%d - using %dx%d",
                            index, config.CAMERA_WIDTH, config.CAMERA_HEIGHT, w, h)
            log.info("Camera %d opened (backend %s, %dx%d)", index, backend, w, h)
            return cap
        cap.release()
    raise CameraError(
        f"Cannot open camera {index}. Check: Windows Settings > Privacy & security > Camera "
        "(allow desktop apps), close Zoom/Teams/Browser tabs using the camera, or pick another camera number."
    )


def draw_overlay(frame: np.ndarray, observations: dict, raw_by_arm: dict, fps: float) -> None:
    """Draw skeletons, labels and the HANDSYNC HUD directly on the BGR frame."""
    h, w = frame.shape[:2]
    for arm, raw in raw_by_arm.items():
        color = ARM_COLORS[arm]
        pts = [(int(p[0] * w), int(p[1] * h)) for p in raw.landmarks]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], color, 2, cv2.LINE_AA)
        for i, p in enumerate(pts):
            cv2.circle(frame, p, 5 if i in (0, 4, 8, 12, 16, 20) else 3, (255, 255, 255), -1, cv2.LINE_AA)
        obs = observations.get(arm)
        gesture = obs.gesture if obs else NEUTRAL
        cv2.putText(frame, f"{arm.upper()} ARM | {gesture}", (pts[0][0] - 40, min(h - 8, pts[0][1] + 28)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    cv2.rectangle(frame, (0, 0), (w, 34), (20, 14, 8), -1)
    cv2.putText(frame, "HANDSYNC", (10, 24), cv2.FONT_HERSHEY_DUPLEX, 0.8, (240, 200, 76), 1, cv2.LINE_AA)
    cv2.putText(frame, f"FPS {fps:4.1f}   HANDS {len(raw_by_arm)}", (w - 210, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1, cv2.LINE_AA)
    legend = "PINCH = CLOSE | OPEN PALM = OPEN | FIST = HOLD"
    cv2.rectangle(frame, (0, h - 30), (w, h), (20, 14, 8), -1)
    cv2.putText(frame, legend, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 200, 76), 1, cv2.LINE_AA)


class CameraWorker(QThread):
    result_ready = Signal(object)        # FrameResult
    camera_status = Signal(bool, str)    # ok?, message
    fatal_error = Signal(str)            # human readable; worker stops afterwards

    def __init__(self, camera_index: int, mirror: bool, swap: bool, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.mirror = mirror
        self.swap = swap
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:  # noqa: C901 - one linear loop, kept together on purpose
        tracker: Optional[HandTracker] = None
        cap = None
        try:
            tracker = HandTracker()
            cap = open_camera(self.camera_index)
        except (HandTrackerError, CameraError) as exc:
            log.error("Worker start failed: %s", exc)
            self.fatal_error.emit(str(exc))
            self._cleanup(cap, tracker)
            return
        except Exception as exc:
            log.exception("Unexpected worker start failure")
            self.fatal_error.emit(f"Unexpected error while starting: {exc}")
            self._cleanup(cap, tracker)
            return

        self.camera_status.emit(True, "OK")
        debouncers = {arm: GestureDebouncer() for arm in config.ARMS}
        previous_gesture = {arm: NEUTRAL for arm in config.ARMS}
        failures, fps, last = 0, 0.0, time.perf_counter()
        start = time.perf_counter()
        self._running = True
        while self._running:
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                if failures >= config.CAMERA_MAX_READ_FAILURES:
                    self.fatal_error.emit("Camera disconnected or stopped sending frames.")
                    break
                time.sleep(0.01)
                continue
            failures = 0
            try:
                mirror, swap = self.mirror, self.swap
                if mirror:
                    frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                hands = tracker.detect(rgb, int((time.perf_counter() - start) * 1000))
                by_arm = assign_arms(hands, mirrored_input=mirror, swap=swap)
                observations: dict = {}
                for arm in config.ARMS:
                    raw: Optional[RawHand] = by_arm.get(arm)
                    if raw is None:
                        debouncers[arm].reset()
                        previous_gesture[arm] = NEUTRAL
                        observations[arm] = None
                        continue
                    feats = analyze_hand(raw.landmarks, mirror=mirror, aspect=w / h)
                    previous_gesture[arm] = classify_gesture(feats, previous_gesture[arm])
                    stable = debouncers[arm].update(previous_gesture[arm])
                    observations[arm] = HandObservation(arm, raw.label, feats, stable)
                now = time.perf_counter()
                instant_fps = 1.0 / max(now - last, 1e-6)
                fps = instant_fps if not fps else 0.9 * fps + 0.1 * instant_fps
                last = now
                draw_overlay(frame, observations, by_arm, fps)
                rgb_out = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = QImage(rgb_out.data, w, h, 3 * w, QImage.Format_RGB888).copy()
                self.result_ready.emit(FrameResult(image, observations, fps, len(by_arm)))
            except Exception as exc:
                log.exception("Frame processing error")
                self.fatal_error.emit(f"Hand tracking error: {exc}")
                break
        self._cleanup(cap, tracker)

    @staticmethod
    def _cleanup(cap, tracker) -> None:
        if cap is not None:
            cap.release()
        if tracker is not None:
            tracker.close()
