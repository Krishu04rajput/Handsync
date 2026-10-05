"""Exhibition DEMO mode: a timed, self-explaining sequence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# (mode, caption, seconds).  Modes: home | track | gripper_close | gripper_open
DEMO_STEPS = (
    ("home", "1/7  ROBOT GOES TO HOME POSITION", 4.0),
    ("track", "2/7  SHOW YOUR HANDS TO THE CAMERA", 5.0),
    ("track", "3/7  MOVE YOUR HANDS - THE ROBOT MIRRORS THEM", 12.0),
    ("track", "4/7  OPEN PALM = OPEN  |  PINCH = CLOSE  |  FIST = HOLD", 10.0),
    ("gripper_close", "5/7  AUTOMATIC GRIPPER TEST: CLOSING", 2.0),
    ("gripper_open", "6/7  AUTOMATIC GRIPPER TEST: OPENING", 2.0),
    ("home", "7/7  RETURNING HOME - THANK YOU!", 4.0),
)


@dataclass
class DemoCommand:
    mode: str
    caption: str
    step: int


class DemoSequencer:
    def __init__(self, steps=DEMO_STEPS):
        self.steps = steps
        self.active = False
        self._started = 0.0

    def start(self, now: float) -> None:
        self.active, self._started = True, now

    def stop(self) -> None:
        self.active = False

    def update(self, now: float) -> DemoCommand:
        """Current command; mode 'done' (and active=False) once the sequence has finished."""
        elapsed = now - self._started
        for index, (mode, caption, seconds) in enumerate(self.steps):
            if elapsed < seconds:
                return DemoCommand(mode, caption, index)
            elapsed -= seconds
        self.active = False
        return DemoCommand("done", "DEMO FINISHED", len(self.steps))
