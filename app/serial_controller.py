"""USB serial link to the ESP32 (PySerial).

Protocol (one text line per message, '\\n' terminated):
    PC -> ESP32:  "90,80,110,90,90,100,70,30"   8 angles, channel order 0..7
                  STOP | RESUME | ENABLE | DISABLE | HOME | PING
    ESP32 -> PC:  "STATUS,<STATE>,<ms since last packet>,<invalid count>", "OK ...", "ERR ...", "WARN ..."
"""
from __future__ import annotations

import re
from typing import Optional, Sequence

try:
    import serial
    from serial.tools import list_ports
except ImportError:           # reported nicely by main.py; keeps pure functions importable for tests
    serial = None             # type: ignore[assignment]
    list_ports = None         # type: ignore[assignment]

import config
from app.logger import get_logger

log = get_logger(__name__)

_INT_RE = re.compile(r"^[+-]?\d{1,3}$")
KNOWN_STATES = ("DISABLED", "ENABLED", "ESTOP", "SAFE_HOLD")


# ------------------------------------------------------------------ pure helpers (unit-tested)
def build_packet(angles: Sequence[float]) -> str:
    """'a,b,c,d,e,f,g,h\\n' with every angle rounded and limited to 0..180."""
    if len(angles) != config.NUM_SERVOS:
        raise ValueError(f"expected {config.NUM_SERVOS} angles, got {len(angles)}")
    values = [int(min(max(round(a), 0), 180)) for a in angles]
    return ",".join(str(v) for v in values) + "\n"


def parse_packet(line: str) -> list[int]:
    """Parse an angle packet exactly like the ESP32 does. Raises ValueError if invalid."""
    parts = line.strip().split(",")
    if len(parts) != config.NUM_SERVOS:
        raise ValueError(f"expected {config.NUM_SERVOS} values, got {len(parts)}")
    out = []
    for part in parts:
        if not _INT_RE.match(part.strip()):
            raise ValueError(f"not an integer: {part!r}")
        value = int(part)
        if not 0 <= value <= 180:
            raise ValueError(f"angle {value} outside 0..180")
        out.append(value)
    return out


def parse_status(line: str) -> Optional[dict]:
    """Parse 'STATUS,ENABLED,120,0' -> {'state': 'ENABLED', 'age_ms': 120, 'invalid': 0}; else None."""
    parts = line.strip().split(",")
    if len(parts) < 2 or parts[0] != "STATUS" or parts[1] not in KNOWN_STATES:
        return None
    info = {"state": parts[1], "age_ms": 0, "invalid": 0}
    try:
        if len(parts) > 2:
            info["age_ms"] = int(parts[2])
        if len(parts) > 3:
            info["invalid"] = int(parts[3])
    except ValueError:
        return None
    return info


# ------------------------------------------------------------------ controller
class SerialController:
    def __init__(self, baud: int = config.BAUD_RATE):
        self.baud = baud
        self._ser = None
        self._rx_buffer = b""
        self.port: Optional[str] = None
        self.last_error: str = ""
        self.invalid_rx = 0

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    @staticmethod
    def list_ports() -> list[tuple[str, str]]:
        """[(device, description)] for every serial port Windows currently sees."""
        if list_ports is None:
            return []
        try:
            return [(p.device, p.description) for p in sorted(list_ports.comports(), key=lambda p: p.device)]
        except Exception as exc:
            log.error("Port scan failed: %s", exc)
            return []

    def connect(self, port: str) -> bool:
        if serial is None:
            self.last_error = "PySerial is not installed. Run: python -m pip install -r requirements.txt"
            return False
        if not port:
            self.last_error = "No COM port selected."
            return False
        self.disconnect()
        try:
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = self.baud
            ser.timeout = 0
            ser.write_timeout = config.SERIAL_WRITE_TIMEOUT_S
            ser.dtr = False      # avoid auto-reset on open where the adapter allows it
            ser.rts = False
            ser.open()
        except Exception as exc:
            self.last_error = f"Cannot open {port}: {exc}. Is another program (Arduino IDE Serial Monitor) using it?"
            log.error(self.last_error)
            self._ser = None
            return False
        self._ser, self.port, self._rx_buffer, self.last_error = ser, port, b"", ""
        log.info("Serial connected on %s @ %d baud", port, self.baud)
        return True

    def reconnect(self) -> bool:
        return self.connect(self.port) if self.port else False

    def disconnect(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            log.info("Serial disconnected (%s)", self.port)
        self._ser = None

    def _write(self, text: str) -> bool:
        if not self.is_connected:
            return False
        try:
            self._ser.write(text.encode("ascii"))
            return True
        except Exception as exc:
            self.last_error = f"Serial write failed: {exc}"
            log.error(self.last_error)
            self.disconnect()
            return False

    def send_angles(self, angles: Sequence[float]) -> bool:
        return self._write(build_packet(angles))

    def send_command(self, command: str) -> bool:
        return self._write(command.strip().upper() + "\n")

    def poll(self) -> list[str]:
        """Read whatever the ESP32 sent (non-blocking). Returns complete text lines."""
        if not self.is_connected:
            return []
        try:
            waiting = self._ser.in_waiting
            data = self._ser.read(waiting) if waiting else b""
        except Exception as exc:
            self.last_error = f"Serial read failed: {exc}"
            log.error(self.last_error)
            self.disconnect()
            return []
        if not data:
            return []
        self._rx_buffer = (self._rx_buffer + data)[-2048:]
        *lines, self._rx_buffer = self._rx_buffer.split(b"\n")
        out = []
        for raw in lines:
            text = raw.decode("ascii", errors="ignore").strip()
            if text and all(32 <= ord(c) < 127 for c in text):
                out.append(text)
            elif text:
                self.invalid_rx += 1      # boot garbage / noise
        return out
