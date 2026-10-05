"""HANDSYNC central configuration.

Edit values here instead of searching through the code.
NOTE: servo limits / invert / open-close angles can also be changed from the
CALIBRATION window; those are stored in config/calibration.json and override
the defaults below.
"""
from __future__ import annotations

from pathlib import Path

APP_NAME = "HANDSYNC"
APP_SUBTITLE = "COMPUTER VISION \u2192 ESP32 \u2192 DUAL ROBOTIC ARMS"

# ---------------------------------------------------------------- paths
BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
MODEL_PATH = MODELS_DIR / "hand_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_MIN_BYTES = 1_000_000          # a real model is ~7.8 MB; smaller = broken download
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "handsync.log"
CALIBRATION_FILE = BASE_DIR / "config" / "calibration.json"

# ---------------------------------------------------------------- camera
CAMERA_INDEX = 0
CAMERA_INDEX_CHOICES = [0, 1, 2, 3, 4]
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_MAX_READ_FAILURES = 45        # consecutive failed reads before "camera disconnected"
MIRROR_CAMERA_DEFAULT = True         # flip preview like a mirror
SWAP_LEFT_RIGHT_DEFAULT = False      # saved value in calibration.json wins

# ---------------------------------------------------------------- MediaPipe Hand Landmarker (Tasks API)
MAX_HANDS = 2
MIN_HAND_DETECTION_CONFIDENCE = 0.5
MIN_HAND_PRESENCE_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5

# ---------------------------------------------------------------- serial
BAUD_RATE = 115200
SERIAL_WRITE_TIMEOUT_S = 0.1
CONTROL_RATE_HZ = 25                 # packets/second sent to the ESP32 (also the heartbeat)
ESP32_TIMEOUT_MS = 750               # informational: must match COMMAND_TIMEOUT_MS in the .ino

# ---------------------------------------------------------------- servos
# ORDER MATTERS: index in this tuple == PCA9685 channel == position in serial packet.
SERVO_NAMES = (
    "left_base", "left_shoulder", "left_elbow", "left_gripper",
    "right_base", "right_shoulder", "right_elbow", "right_gripper",
)
NUM_SERVOS = len(SERVO_NAMES)
SERVO_CHANNELS = {name: index for index, name in enumerate(SERVO_NAMES)}
ARMS = ("left", "right")
JOINTS = ("base", "shoulder", "elbow", "gripper")

# Default safe limits per joint (min, max) in degrees. Same on both arms.
DEFAULT_LIMITS = {
    "base": (20, 160),
    "shoulder": (25, 150),
    "elbow": (25, 150),
    "gripper": (25, 100),
}
HOME_ANGLE = 90
GRIPPER_OPEN_DEFAULT = 90
GRIPPER_CLOSED_DEFAULT = 30

# ---------------------------------------------------------------- smoothing
SMOOTHING_ALPHA = 0.20               # 0..1, higher = faster but more jitter
MAX_STEP_PER_UPDATE = 3.0            # degrees per control tick (3 * 25 Hz = 75 deg/s)
DEADBAND_DEG = 0.6                   # ignore changes smaller than this
INPUT_SMOOTHING = 0.45               # light filter on raw hand position before mapping

# ---------------------------------------------------------------- hand -> angle mapping
ACTIVE_X_RANGE = (0.15, 0.85)        # part of the image (0..1) that maps to full base range
ACTIVE_Y_RANGE = (0.15, 0.85)        # part of the image that maps to full shoulder range
TILT_RANGE_DEG = 40.0                # hand tilt (+/-) that maps to full elbow range
MAPPING_DEADZONE = 0.04              # normalised dead zone around centre (-1..1 scale)
HAND_LOSS_HOLD_S = 0.7               # "tracking uncertain" window after a hand disappears

# ---------------------------------------------------------------- gestures
GESTURE_FIST_MAX_OPENNESS = 1.30     # mean finger extension of middle/ring/pinky below this = fist
GESTURE_OPEN_MIN_OPENNESS = 1.55     # above this = open palm
PINCH_CLOSE_RATIO = 0.35             # thumb-index distance / palm size below this = pinch
PINCH_RELEASE_RATIO = 0.55           # must exceed this to leave pinch (hysteresis)
GESTURE_DEBOUNCE_FRAMES = 3          # frames a new gesture must persist

# ---------------------------------------------------------------- UI
HOME_DONE_TOLERANCE_DEG = 1.0
