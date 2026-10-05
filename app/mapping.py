"""Hand observations -> robot joint targets (before smoothing).

Mapping (all values normalised to -1..+1 first, then converted to servo angles):
    palm X position   -> BASE      (hand moves right  -> base turns toward +)
    palm Y position   -> SHOULDER  (hand moves up     -> shoulder toward +)
    hand tilt (roll)  -> ELBOW     (fingers lean right-> elbow toward +)
    gesture           -> GRIPPER   (OPEN palm = open, PINCH = closed, FIST/neutral = hold)
Use the 'invert' option in calibration if a joint moves the wrong way on your robot.
"""
from __future__ import annotations

from typing import Optional

import config
from app.calibration import Calibration, ServoCalibration
from app.gesture import GripperLogic, HandObservation
from app.smoothing import ExponentialSmoother


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def remap_to_norm(value: float, low: float, high: float) -> float:
    """Map value in [low, high] to [-1, +1] (clamped)."""
    if high == low:
        return 0.0
    return clamp((value - low) / (high - low) * 2.0 - 1.0, -1.0, 1.0)


def apply_deadzone(norm: float, dead: float) -> float:
    """Zero inside +/-dead, rescale the rest so the output still reaches +/-1."""
    if abs(norm) <= dead:
        return 0.0
    sign = 1.0 if norm > 0 else -1.0
    return sign * (abs(norm) - dead) / (1.0 - dead)


def norm_to_angle(norm: float, servo: ServoCalibration) -> float:
    """-1..+1 -> angle: 0 is the centre angle, -1 is min, +1 is max."""
    norm = clamp(norm, -1.0, 1.0)
    if norm >= 0:
        return servo.center + norm * (servo.max - servo.center)
    return servo.center + norm * (servo.center - servo.min)


class RobotMapper:
    """Keeps the latest joint targets for both arms. Holds the last pose when a hand is lost."""

    def __init__(self, calibration: Calibration):
        self.cal = calibration
        self._filters: dict[str, dict[str, ExponentialSmoother]] = {}
        self._grippers: dict[str, GripperLogic] = {}
        self._last_seen: dict[str, float] = {}
        self._logical: dict[str, float] = {}
        self.reset()

    def set_calibration(self, calibration: Calibration) -> None:
        self.cal = calibration

    def reset(self) -> None:
        """Back to centre pose with open grippers (used at start and after HOME)."""
        for arm in config.ARMS:
            self._filters[arm] = {k: ExponentialSmoother(config.INPUT_SMOOTHING) for k in ("x", "y", "tilt")}
            self._grippers[arm] = GripperLogic(start_open=True)
        self._last_seen = {}
        self._logical = {n: float(self.cal.servos[n].center) for n in config.SERVO_NAMES}

    def update(self, observations: dict[str, Optional[HandObservation]], now: float) -> None:
        for arm in config.ARMS:
            obs = observations.get(arm)
            if obs is None:
                continue     # hand lost: keep last targets (never jump)
            self._last_seen[arm] = now
            f, flt = obs.features, self._filters[arm]
            x = flt["x"].update(f.palm_x)
            y = flt["y"].update(f.palm_y)
            tilt = flt["tilt"].update(f.tilt_deg)
            dz = config.MAPPING_DEADZONE
            base_n = apply_deadzone(remap_to_norm(x, *config.ACTIVE_X_RANGE), dz)
            shoulder_n = apply_deadzone(-remap_to_norm(y, *config.ACTIVE_Y_RANGE), dz)   # up = +
            elbow_n = apply_deadzone(clamp(tilt / config.TILT_RANGE_DEG, -1.0, 1.0), dz)
            for joint, norm in (("base", base_n), ("shoulder", shoulder_n), ("elbow", elbow_n)):
                name = f"{arm}_{joint}"
                self._logical[name] = norm_to_angle(norm, self.cal.servos[name])
            self._grippers[arm].update(obs.gesture)

    def tracking_state(self, arm: str, now: float) -> str:
        """'TRACKING' (seen now), 'UNCERTAIN' (lost recently, holding pose) or 'LOST'."""
        seen = self._last_seen.get(arm)
        if seen is None:
            return "LOST"
        age = now - seen
        if age < 0.15:
            return "TRACKING"
        return "UNCERTAIN" if age < config.HAND_LOSS_HOLD_S else "LOST"

    def targets(self) -> list[int]:
        """Final (inverted + clamped) servo angles in channel order."""
        out: list[int] = []
        for name in config.SERVO_NAMES:
            arm, joint = name.split("_", 1)
            if joint == "gripper":
                out.append(self.cal.gripper_angle(arm, self._grippers[arm].is_open))
            else:
                out.append(self.cal.to_output(name, self._logical[name]))
        return out
