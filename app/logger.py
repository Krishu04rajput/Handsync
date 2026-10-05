"""Logging to logs/handsync.log (+ console)."""
from __future__ import annotations

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler

import config

_CONFIGURED = False


def setup_logging() -> logging.Logger:
    """Create the log folder/handlers once and log basic system information."""
    global _CONFIGURED
    root = logging.getLogger("handsync")
    if _CONFIGURED:
        return root
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    try:
        file_handler = RotatingFileHandler(
            config.LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:  # read-only folder etc. - never crash because of logging
        print(f"WARNING: cannot write log file: {exc}", file=sys.stderr)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    _CONFIGURED = True
    root.info("=== HANDSYNC starting ===")
    root.info("Python %s | %s", sys.version.replace("\n", " "), platform.platform())
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a child logger of 'handsync'."""
    short = name.split(".")[-1] if name != "__main__" else "main"
    return logging.getLogger(f"handsync.{short}")
