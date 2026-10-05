"""Servo calibration: limits, centre, inversion, gripper open/closed, left/right swap."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import config
from app.logger import get_logger

log = get_logger(__name__)


class CalibrationError(ValueError):
    """Raised when calibration data is malformed or unsafe."""


@dataclass
class ServoCalibration:
    min: int
    max: int
    center: int
    invert: bool = False
    open: Optional[int] = None     # grippers only: servo angle for "open"
    closed: Optional[int] = None   # grippers only: servo angle for "closed"

    def validate(self, name: str) -> None:
        for field_name in ("min", "max", "center"):
            value = getattr(self, field_name)
            if not 0 <= value <= 180:
                raise CalibrationError(f"{name}.{field_name} = {value} is outside 0..180")
        if not self.min < self.max:
            raise CalibrationError(f"{name}: min ({self.min}) must be smaller than max ({self.max})")
        if not self.min <= self.center <= self.max:
            raise CalibrationError(f"{name}: center ({self.center}) must be between min and max")
        for field_name in ("open", "closed"):
            value = getattr(self, field_name)
            if value is not None and not self.min <= value <= self.max:
                raise CalibrationError(
                    f"{name}.{field_name} = {value} must be between min ({self.min}) and max ({self.max})"
                )


def _to_int(name: str, field: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationError(f"{name}.{field} must be a number, got {value!r}")
    return int(round(value))


def default_servo(name: str) -> ServoCalibration:
    joint = name.split("_", 1)[1]
    lo, hi = config.DEFAULT_LIMITS[joint]
    center = min(max(config.HOME_ANGLE, lo), hi)
    if joint == "gripper":
        return ServoCalibration(lo, hi, center, False,
                                config.GRIPPER_OPEN_DEFAULT, config.GRIPPER_CLOSED_DEFAULT)
    return ServoCalibration(lo, hi, center, False)


class Calibration:
    """All eight servo calibrations plus global settings."""

    def __init__(self, servos: dict[str, ServoCalibration], swap_left_right: bool = False):
        self.servos = servos
        self.swap_left_right = swap_left_right

    # ---- construction -------------------------------------------------
    @classmethod
    def default(cls) -> "Calibration":
        return cls({n: default_servo(n) for n in config.SERVO_NAMES}, config.SWAP_LEFT_RIGHT_DEFAULT)

    @classmethod
    def from_dict(cls, data: Any) -> "Calibration":
        if not isinstance(data, dict):
            raise CalibrationError("calibration file must contain a JSON object")
        servos: dict[str, ServoCalibration] = {}
        for name in config.SERVO_NAMES:
            cal = default_servo(name)
            entry = data.get(name)
            if entry is not None:
                if not isinstance(entry, dict):
                    raise CalibrationError(f"'{name}' must be an object")
                for field in ("min", "max", "center"):
                    if field in entry:
                        setattr(cal, field, _to_int(name, field, entry[field]))
                if "invert" in entry:
                    if not isinstance(entry["invert"], bool):
                        raise CalibrationError(f"{name}.invert must be true or false")
                    cal.invert = entry["invert"]
                for field in ("open", "closed"):
                    if field in entry and entry[field] is not None:
                        setattr(cal, field, _to_int(name, field, entry[field]))
            cal.validate(name)
            servos[name] = cal
        settings = data.get("settings", {})
        if not isinstance(settings, dict):
            raise CalibrationError("'settings' must be an object")
        swap = settings.get("swap_left_right", config.SWAP_LEFT_RIGHT_DEFAULT)
        if not isinstance(swap, bool):
            raise CalibrationError("settings.swap_left_right must be true or false")
        return cls(servos, swap)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in config.SERVO_NAMES:
            s = self.servos[name]
            entry: dict[str, Any] = {"min": s.min, "max": s.max, "center": s.center, "invert": s.invert}
            if s.open is not None:
                entry["open"] = s.open
            if s.closed is not None:
                entry["closed"] = s.closed
            out[name] = entry
        out["settings"] = {"swap_left_right": self.swap_left_right}
        return out

    # ---- safety / conversion -----------------------------------------
    def clamp(self, name: str, angle: float) -> int:
        """Force an angle into the servo's configured safe range."""
        s = self.servos[name]
        return int(min(max(round(angle), s.min), s.max))

    def to_output(self, name: str, logical_angle: float) -> int:
        """Apply inversion around the centre angle, then clamp to limits."""
        s = self.servos[name]
        angle = 2 * s.center - logical_angle if s.invert else logical_angle
        return self.clamp(name, angle)

    def home_outputs(self) -> list[int]:
        return [self.clamp(n, self.servos[n].center) for n in config.SERVO_NAMES]

    def gripper_angle(self, arm: str, open_: bool) -> int:
        name = f"{arm}_gripper"
        s = self.servos[name]
        value = s.open if open_ else s.closed
        if value is None:
            value = s.max if open_ else s.min
        return self.clamp(name, value)

    def copy(self) -> "Calibration":
        return Calibration.from_dict(self.to_dict())


def save_calibration(cal: Calibration, path: Path = config.CALIBRATION_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cal.to_dict(), fh, indent=4)
    log.info("Calibration saved to %s", path)


def load_calibration(path: Path = config.CALIBRATION_FILE) -> tuple[Calibration, list[str]]:
    """Load calibration. Never raises: on any problem returns defaults + warning messages."""
    warnings: list[str] = []
    if not path.exists():
        cal = Calibration.default()
        try:
            save_calibration(cal, path)
            log.info("No calibration file found - created defaults at %s", path)
        except OSError as exc:
            warnings.append(f"Could not create calibration file: {exc}")
        return cal, warnings
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        cal = Calibration.from_dict(data)
        log.info("Calibration loaded from %s", path)
        return cal, warnings
    except json.JSONDecodeError as exc:
        msg = f"calibration.json is not valid JSON ({exc}). Using safe default limits."
    except CalibrationError as exc:
        msg = f"Invalid calibration: {exc}. Using safe default limits."
    except OSError as exc:
        msg = f"Cannot read calibration file: {exc}. Using safe default limits."
    log.error(msg)
    warnings.append(msg)
    return Calibration.default(), warnings
