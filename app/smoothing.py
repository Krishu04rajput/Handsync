"""Smoothing helpers: exponential filter, per-servo step limiter, deadband."""
from __future__ import annotations

from typing import Optional, Sequence


class ExponentialSmoother:
    """Single-value exponential moving average (low-pass filter)."""

    def __init__(self, alpha: float):
        self.alpha = alpha
        self.value: Optional[float] = None

    def update(self, new_value: float) -> float:
        if self.value is None:
            self.value = new_value
        else:
            self.value += self.alpha * (new_value - self.value)
        return self.value

    def reset(self) -> None:
        self.value = None


class ServoSmoother:
    """Moves a list of servo angles toward targets.

    Each call to step():  delta = alpha * error, limited to +/- max_step,
    and ignored entirely when |error| < deadband.
    """

    def __init__(self, initial: Sequence[float], alpha: float, max_step: float, deadband: float):
        self.alpha = alpha
        self.max_step = max_step
        self.deadband = deadband
        self.values: list[float] = [float(v) for v in initial]

    def reset(self, values: Sequence[float]) -> None:
        self.values = [float(v) for v in values]

    def step(self, targets: Sequence[float]) -> list[float]:
        if len(targets) != len(self.values):
            raise ValueError("targets length does not match smoother size")
        for i, target in enumerate(targets):
            error = target - self.values[i]
            if abs(error) < self.deadband:
                continue
            delta = error * self.alpha
            # alpha*error becomes tiny near the target; keep a small minimum push so we arrive
            min_push = min(abs(error), 0.5)
            if abs(delta) < min_push:
                delta = min_push if error > 0 else -min_push
            delta = max(-self.max_step, min(self.max_step, delta))
            self.values[i] += delta
        return list(self.values)

    def max_error(self, targets: Sequence[float]) -> float:
        return max(abs(t - v) for t, v in zip(targets, self.values))
