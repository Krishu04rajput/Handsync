"""HANDSYNC entry point:  python main.py"""
from __future__ import annotations

import importlib.util
import sys

REQUIRED_PACKAGES = [          # (import name, pip name)
    ("PySide6", "PySide6"),
    ("cv2", "opencv-contrib-python"),
    ("numpy", "numpy"),
    ("mediapipe", "mediapipe"),
    ("serial", "pyserial"),
]


def missing_packages() -> list[str]:
    return [pip for module, pip in REQUIRED_PACKAGES if importlib.util.find_spec(module) is None]


def main() -> int:
    from app.logger import setup_logging
    log = setup_logging()

    if importlib.util.find_spec("PySide6") is None:
        print("\nHANDSYNC cannot start: PySide6 is not installed.\n"
              "Run:  python -m pip install -r requirements.txt\n")
        input("Press Enter to close...")
        return 1

    from PySide6.QtWidgets import QApplication, QMessageBox
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")

    missing = missing_packages()
    if missing:
        log.error("Missing packages: %s", missing)
        QMessageBox.critical(None, "HANDSYNC - missing packages",
                             "These Python packages are missing:\n\n  " + "\n  ".join(missing) +
                             "\n\nRun this in PowerShell inside the HANDSYNC folder:\n\n"
                             "  python -m pip install -r requirements.txt")
        return 1

    def excepthook(exc_type, exc, tb):
        log.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        QMessageBox.critical(None, "HANDSYNC - unexpected error",
                             f"{exc_type.__name__}: {exc}\n\nDetails were written to logs/handsync.log")

    sys.excepthook = excepthook

    from app.calibration import load_calibration
    from app.ui import MainWindow

    calibration, warnings = load_calibration()
    window = MainWindow(calibration, warnings)
    window.show()
    return qt_app.exec()


if __name__ == "__main__":
    sys.exit(main())
