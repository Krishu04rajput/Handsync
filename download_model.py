"""Download the MediaPipe Hand Landmarker model:  python download_model.py"""
import sys

import config
from app.hand_tracker import HandTrackerError, download_model, model_status

ok, _ = model_status()
if ok:
    print(f"Model already present: {config.MODEL_PATH}")
    sys.exit(0)
print(f"Downloading model to {config.MODEL_PATH} ...")
try:
    download_model()
except HandTrackerError as exc:
    print(f"\nFAILED:\n{exc}")
    sys.exit(1)
print("Done.")
