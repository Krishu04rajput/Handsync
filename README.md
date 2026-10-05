# HANDSYNC
**Computer Vision → ESP32 → PCA9685 → Dual Robotic Arms** (school exhibition project)

Your laptop webcam sees your hands. Python (OpenCV + MediaPipe Hand Landmarker) turns hand position and
gestures into 8 servo angles and sends them over USB serial to an ESP32. The ESP32 drives a PCA9685
servo board, which moves two 4-servo robotic arms.

```
HANDS → WEBCAM → OpenCV → MediaPipe Hand Landmarker → gestures + joint angles → smoothing + safety limits
      → PySide6 dashboard → USB serial → ESP32 → I2C → PCA9685 → 8 servos → two arms
```

## 1. Honest status of this package
* The pure-Python logic (calibration, smoothing, gestures, mapping, serial packets, demo timing) has unit tests that pass.
* The PySide6 window, the MediaPipe call and the ESP32 sketch could **not** be run where this was written
  (no GUI, no webcam, no ESP32, no internet). They were written against the documented APIs and checked by
  reading/static checks. **Follow the test steps in section 12 in order** and report any error from `logs/handsync.log`.

## 2. Python version and dependencies (important)
* Use **Python 3.12, 64-bit**. `requirements.txt` pins `mediapipe==0.10.21`, `numpy==1.26.4`,
  `opencv-contrib-python==4.10.0.84`, `PySide6==6.7.3`, `pyserial==3.5`.
* MediaPipe 0.10.21 needs `numpy<2` and ships its own OpenCV; **do not install `opencv-python` as well**.
* The code uses only `mediapipe.tasks.python.vision.HandLandmarker` – never `mp.solutions`. That is why
  the old `module 'mediapipe' has no attribute 'solutions'` error cannot happen.
* Python 3.13/3.14 + NumPy 2.x + OpenCV 5 + MediaPipe 1.0.x was **not** tested. If you want to try it, edit
  `requirements.txt`, install, and check that `HandLandmarker`, `HandLandmarkerOptions`, `RunningMode`, `BaseOptions`
  and `mp.Image` still exist. Otherwise just install Python 3.12 next to your current one (they can coexist).

## 3. Windows installation (PowerShell)
```powershell
cd "C:\Users\YOURNAME\Desktop\HANDSYNC"
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python download_model.py
python main.py
```
If PowerShell blocks `Activate.ps1`: `Set-ExecutionPolicy -Scope Process Bypass`, then activate again.
Easier: double-click **setup_windows.bat** once, then **run_windows.bat** every time.
Without a venv: `python -m pip install -r requirements.txt` then `python main.py` (or `py main.py`).

### The MediaPipe model file
`models/hand_landmarker.task` (~8 MB) is downloaded by `setup_windows.bat`, by `python download_model.py`,
or by the **Download now** button that appears when you press START CAMERA and the model is missing.
Manual download: `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task`
→ save as `HANDSYNC\models\hand_landmarker.task`.

## 4. Project layout
```
main.py  config.py  requirements.txt  setup_windows.bat  run_windows.bat  download_model.py
app/   ui.py camera.py hand_tracker.py gesture.py mapping.py smoothing.py serial_controller.py
       calibration.py demo.py logger.py
config/calibration.json    models/hand_landmarker.task    logs/handsync.log
esp32/HANDSYNC_ESP32/HANDSYNC_ESP32.ino    tests/
```
`config.py` = all tunable numbers. `config/calibration.json` = per-servo limits (edited in the CALIBRATION window).

## 5. Robot states (safety model)
| State | Meaning |
|---|---|
| VISION ONLY | ESP32 not connected. Camera/gestures work, nothing moves. |
| ROBOT DISABLED | ESP32 connected, servos not driven. **Default.** |
| ROBOT ENABLED | You pressed ENABLE ROBOT. Servos follow commands (soft start from HOME). |
| EMERGENCY STOP | `STOP` sent; nothing moves until you press RESUME. Hotkey: **Esc**. |

Other safety layers: limits enforced in Python *and again* in the ESP32; smoothing + max step per update in Python;
slew-rate limit on the ESP32; 25 Hz heartbeat and a 750 ms timeout (ESP32 freezes in SAFE_HOLD if packets stop);
no servo signal at all after ESP32 boot until ENABLE; lost hand = robot **holds** its pose.
A software stop is not a substitute for a **physical switch on the servo power supply** – fit one.

## 6. Serial protocol (115200 baud, text lines ending in `\n`)
PC → ESP32: `90,80,110,90,90,100,70,30` (8 angles) · `PING` · `ENABLE` · `DISABLE` · `HOME` · `STOP` · `RESUME` · `STATUS`
ESP32 → PC: `STATUS,<STATE>,<ms since packet>,<invalid count>` every 500 ms, plus `OK …`, `ERR …`, `WARN …`.

| Channel | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| Servo | L base | L shoulder | L elbow | L gripper | R base | R shoulder | R elbow | R gripper |

## 7. Hand → robot mapping
Palm X → base · palm Y (up = +) → shoulder · hand tilt (fingers leaning right = +) → elbow ·
OPEN palm → gripper open · PINCH → closed · FIST/neutral → hold. If a joint moves the wrong way,
tick **Invert** in CALIBRATION. Gripper open/closed angles are set there too (gripper = direct angles).
Handedness: frames are mirrored by default and MediaPipe assumes a mirrored image, so your *left* hand drives the *left* arm.
If it is the other way round on your setup, tick **SWAP LEFT / RIGHT** (saved automatically).

## 8. ESP32 and wiring
1. Arduino IDE → install ESP32 board support, then Library Manager → **Adafruit PWM Servo Driver Library**.
2. Open `esp32/HANDSYNC_ESP32/HANDSYNC_ESP32.ino`, board "ESP32 Dev Module", upload. Close Serial Monitor afterwards.
3. Wiring (ESP32 DevKit default pins; change `SDA_PIN/SCL_PIN` in the sketch if needed):

| ESP32 | PCA9685 |
|---|---|
| 3V3 | VCC (logic power) |
| GND | GND |
| GPIO21 | SDA |
| GPIO22 | SCL |

Servos plug into PCA9685 channels 0–7 (brown/black = GND, red = V+, orange/yellow = signal).

### Servo power – READ THIS
* **Never power 8 SG90 servos from the ESP32 or from USB.** Use a separate regulated **5–6 V supply, ≥ 3 A**
  (8 servos can spike far above the 0.5 A of a USB port).
* Supply **+** → PCA9685 **V+** screw terminal. Supply **GND** → PCA9685 **GND**, and PCA9685 GND ↔ ESP32 GND (common ground).
* The ESP32 only sends logic/I2C. Brown-outs from servo current spikes make the ESP32 reset – add a 470–1000 µF
  capacitor across the V+/GND terminals and keep servo wires short.
* Check pulse limits (`SERVO_MIN_US/MAX_US`, default 500–2400 µs) against your servos.

## 9. Using the app
1. **ESP32 CONNECTION**: REFRESH PORTS → pick the COM port (Device Manager → Ports) → CONNECT. Waits ~2 s if the board reboots.
2. **CAMERA**: choose index (0 = built-in) → START CAMERA.
3. **MODE**: MIRROR (hands drive robot) or MANUAL (sliders drive robot; use for hardware debugging).
4. **ENABLE ROBOT** to allow movement. **HOME ROBOT** moves all servos to centre. **EMERGENCY STOP** / Esc stops; **RESUME** continues.
5. **HARDWARE TEST**: pick one servo, then −45° / CENTER / +45° (always inside the calibrated limits).
6. **START DEMO**: 7-step self-explaining sequence for visitors (home → show hands → mirror → gestures → gripper test → home).
7. **RESPONSE** slider = smoothing speed. Defaults are in `config.py` (`SMOOTHING_ALPHA`, `MAX_STEP_PER_UPDATE`, `DEADBAND_DEG`).

## 10. Calibration
CALIBRATION window edits Min / Center / Max / Invert per servo and Open/Closed for grippers; saved to `config/calibration.json`
and loaded at start. Invalid files fall back to safe defaults with a warning. Tighten limits until the arm cannot hit its own frame.
Tip: set the limits first with MANUAL mode **before** the arm is connected to the mechanism.

## 11. Run the tests
`python -m pip install -r requirements-dev.txt` then `python -m pytest` (or without pytest: `python run_tests_plain.py` – the
parametrised/`raises` tests need pytest).

## 12. FIRST-TIME TEST ORDER (do not skip steps, do not attach servos early)
1. **Camera only** – `python main.py`, START CAMERA. You see yourself, FPS, "CAMERA: OK". No ESP32 needed.
2. **Hand tracking + gestures** – show both hands. Skeletons appear, HAND STATUS shows TRACKING, the servo monitor numbers move.
   Check OPEN / PINCH / FIST are recognised; check left hand = LEFT ARM label (else SWAP LEFT/RIGHT). Robot is not connected.
3. **ESP32 without servo load** – flash the sketch, wire ESP32+PCA9685 only (no servos, or servos NOT on the mechanism, servo PSU off).
   CONNECT → ESP32 firmware state shows DISABLED. ENABLE ROBOT → ENABLED. Press EMERGENCY STOP → ESTOP; RESUME → ENABLED. Unplug USB → app shows CONNECTION ERROR.
4. **One servo** – servo PSU on, ONE bare servo on channel 0 (horn removed). MANUAL mode → ENABLE → HARDWARE TEST on LEFT BASE.
5. **All servos** – all 8 bare servos, MANUAL sliders and HOME. Then mount horns/arms at centre (90°) and set limits in CALIBRATION.
6. **Full mirroring** – MIRROR mode, ENABLE ROBOT, move slowly first. Then DEMO.

## 13. Troubleshooting
* **"Hand Landmarker model not found"** → press Download now / `python download_model.py` / manual download (section 3).
* **MediaPipe install or import error** → use Python 3.12 64-bit and the pinned requirements (section 2). `python --version` must say 3.12.x.
* **Camera error** → Windows Settings → Privacy & security → Camera → allow camera + "let desktop apps access". Close Zoom/Teams/browser tabs using the camera. Try another index. Unplug/replug USB cameras.
* **Low FPS** → good light, close other apps, lower `CAMERA_WIDTH/HEIGHT` in `config.py`.
* **Port not listed** → install the USB driver for your board's chip (CP210x or CH340), try another USB cable (some are charge-only), press REFRESH.
* **"Cannot open COMx"** → close Arduino Serial Monitor / any other program using the port.
* **ESP32 keeps resetting when servos move** → power problem (section 8): separate supply, common GND, capacitor.
* **Servo jitters/hums** → shaky supply or limits too tight to the mechanical end-stop; widen/relax `SERVO_MIN_US/MAX_US`.
* **Joint moves the wrong way** → CALIBRATION → Invert. **Gripper open/closed swapped** → swap Open/Closed values.
* **"ERR BAD_PACKET" from ESP32** → another program is writing to the port, or wrong baud.
* All errors are also written to `logs/handsync.log`.

## 14. Exhibition procedure
1. Servo PSU **off**. Start laptop, run HANDSYNC, START CAMERA. 2. Connect USB, CONNECT ESP32.
3. Clear the area around the arms, servo PSU **on**. 4. HOME ROBOT, then ENABLE ROBOT.
5. Press **START DEMO** (visitors read the banner). 6. Let visitors try with MIRROR mode; keep a hand near Esc and the PSU switch.
7. At the end: DISABLE ROBOT, PSU off, close the app. Keep a spare USB cable and a printed copy of this README.
