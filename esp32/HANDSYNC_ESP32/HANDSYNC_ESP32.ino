/*
 * HANDSYNC ESP32 firmware  -  USB serial -> PCA9685 -> 8 servos (two 4-DOF arms)
 *
 * Library needed (Arduino IDE > Library Manager):  "Adafruit PWM Servo Driver Library"
 * Board: any "ESP32 Dev Module" (Arduino-ESP32 core 2.x or 3.x).  Serial Monitor must be CLOSED
 * while the HANDSYNC app is connected.
 *
 * ---- Protocol (text lines, 115200 baud, '\n' terminated) --------------------------------
 *  PC -> ESP32
 *    90,80,110,90,90,100,70,30   8 angles: ch0..7 = L base, L shoulder, L elbow, L gripper,
 *                                                     R base, R shoulder, R elbow, R gripper
 *    PING     heartbeat (keeps the link alive when no angles are being sent)
 *    ENABLE   start driving the servos (starts from HOME, ramps to commanded angles)
 *    DISABLE  freeze servos where they are, ignore angle packets
 *    HOME     target = home angles (only while ENABLED)
 *    STOP     EMERGENCY STOP: freeze, ignore everything except RESUME / STATUS
 *    RESUME   leave emergency stop -> ENABLED (holds current position until new packets arrive)
 *    STATUS   print status now
 *  ESP32 -> PC
 *    STATUS,<STATE>,<ms since last valid packet>,<invalid packet count>   (every 500 ms)
 *    OK ...  /  ERR ...  /  WARN ...
 *
 * ---- Safety ---------------------------------------------------------------------------
 *  - At boot NO servo signal is generated (no sweep, no jump). State = DISABLED.
 *  - Servos are only driven after an explicit ENABLE.
 *  - Per-servo min/max limits are enforced here again (independent of the PC).
 *  - Slew-rate limit (MAX_SLEW_DEG_PER_SEC) so even a bad packet cannot snap a servo.
 *  - If no valid packet/PING arrives for COMMAND_TIMEOUT_MS while ENABLED -> SAFE_HOLD
 *    (freeze). A new valid ANGLE packet resumes. EMERGENCY STOP never auto-resumes.
 *  - Servo power MUST come from a separate 5-6 V supply (see README). Share GND only.
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ======================= USER SETTINGS =======================
#define SDA_PIN 21                         // ESP32 DevKit default I2C pins
#define SCL_PIN 22
const uint8_t  PCA9685_ADDRESS        = 0x40;
const uint32_t SERIAL_BAUD            = 115200;
const uint32_t COMMAND_TIMEOUT_MS     = 750;    // keep equal to config.ESP32_TIMEOUT_MS
const float    MAX_SLEW_DEG_PER_SEC   = 120.0f; // fastest allowed servo motion
const uint32_t UPDATE_INTERVAL_MS     = 20;     // servo update loop (50 Hz)
const uint32_t STATUS_INTERVAL_MS     = 500;
const bool     RELEASE_ON_STOP        = false;  // true = servos go limp on STOP, false = hold position
const uint16_t SERVO_MIN_US           = 500;    // SG90 typical 500..2400 us (check your servos!)
const uint16_t SERVO_MAX_US           = 2400;

const uint8_t NUM_SERVOS = 8;
// index = PCA9685 channel = position in the PC packet (must match config.SERVO_NAMES)
//                                  LB  LS  LE  LG  RB  RS  RE  RG
const int MIN_ANGLE [NUM_SERVOS] = { 20, 25, 25, 25, 20, 25, 25, 25 };
const int MAX_ANGLE [NUM_SERVOS] = {160,150,150,100,160,150,150,100 };
const int HOME_ANGLE[NUM_SERVOS] = { 90, 90, 90, 90, 90, 90, 90, 90 };
// =============================================================

enum State { ST_DISABLED, ST_ENABLED, ST_ESTOP, ST_SAFE_HOLD };
const char* STATE_NAMES[] = { "DISABLED", "ENABLED", "ESTOP", "SAFE_HOLD" };

Adafruit_PWMServoDriver pwm(PCA9685_ADDRESS, Wire);

State    state = ST_DISABLED;
float    currentAngle[NUM_SERVOS];
float    targetAngle[NUM_SERVOS];
int      lastTicks[NUM_SERVOS];
bool     outputsActive   = false;   // true once ENABLE has been received at least once
bool     outputsReleased = false;
uint32_t lastPacketMs    = 0;
uint32_t lastUpdateMs    = 0;
uint32_t lastStatusMs    = 0;
uint32_t lastErrorMs     = 0;
uint32_t invalidCount    = 0;

char    lineBuf[96];
uint8_t lineLen = 0;
bool    lineOverflow = false;

// ---------------------------------------------------------------- helpers
uint16_t angleToTicks(float angle) {
  float us = SERVO_MIN_US + (angle / 180.0f) * (SERVO_MAX_US - SERVO_MIN_US);
  return (uint16_t)((us * 4096.0f) / 20000.0f + 0.5f);       // 50 Hz -> 20000 us period, 12-bit
}

void reportError(const char* msg) {                          // rate-limited so noise can't flood
  if (millis() - lastErrorMs > 300) {
    Serial.print("ERR "); Serial.println(msg);
    lastErrorMs = millis();
  }
}

void freezeAtCurrent() {
  for (uint8_t i = 0; i < NUM_SERVOS; i++) targetAngle[i] = currentAngle[i];
}

void writeAllForced() {
  for (uint8_t i = 0; i < NUM_SERVOS; i++) lastTicks[i] = -1;
}

void releaseOutputs() {
  for (uint8_t i = 0; i < NUM_SERVOS; i++) pwm.setPWM(i, 0, 0);   // no pulses = servo limp
  outputsReleased = true;
}

void printStatus() {
  Serial.print("STATUS,"); Serial.print(STATE_NAMES[state]);
  Serial.print(','); Serial.print(millis() - lastPacketMs);
  Serial.print(','); Serial.println(invalidCount);
}

// ---------------------------------------------------------------- command handling
bool parseAngles(char* text, int out[NUM_SERVOS]) {
  uint8_t count = 0;
  char* p = text;
  while (true) {
    if (count >= NUM_SERVOS) return false;
    char* end;
    long v = strtol(p, &end, 10);
    if (end == p) return false;                  // no digits
    if (v < 0 || v > 180) return false;          // hard electrical/mechanical sanity range
    out[count++] = (int)v;
    if (*end == ',') { p = end + 1; continue; }
    if (*end == '\0') break;
    return false;                                // junk after number
  }
  return count == NUM_SERVOS;
}

void handleLine(char* line) {
  while (*line == ' ') line++;
  size_t n = strlen(line);
  while (n > 0 && (line[n - 1] == ' ' || line[n - 1] == '\r')) line[--n] = '\0';
  if (n == 0) return;

  if (!strcmp(line, "PING")) {
    lastPacketMs = millis();
  } else if (!strcmp(line, "STOP")) {
    state = ST_ESTOP;
    freezeAtCurrent();
    if (RELEASE_ON_STOP && outputsActive) releaseOutputs();
    Serial.println("OK ESTOP");
  } else if (!strcmp(line, "RESUME")) {
    if (state == ST_ESTOP) {
      if (outputsReleased && outputsActive) { writeAllForced(); outputsReleased = false; }
      state = ST_ENABLED;
      freezeAtCurrent();
      lastPacketMs = millis();
      Serial.println("OK RESUMED");
    } else {
      Serial.println("ERR NOT_IN_ESTOP");
    }
  } else if (!strcmp(line, "ENABLE")) {
    if (state == ST_ESTOP) { Serial.println("ERR ESTOP_ACTIVE"); return; }
    if (!outputsActive) {                         // first enable after boot: start from HOME
      for (uint8_t i = 0; i < NUM_SERVOS; i++) { currentAngle[i] = HOME_ANGLE[i]; targetAngle[i] = HOME_ANGLE[i]; }
      writeAllForced();
      outputsActive = true;
    }
    state = ST_ENABLED;
    lastPacketMs = millis();
    Serial.println("OK ENABLED");
  } else if (!strcmp(line, "DISABLE")) {
    if (state != ST_ESTOP) { state = ST_DISABLED; freezeAtCurrent(); }
    Serial.println("OK DISABLED");
  } else if (!strcmp(line, "HOME")) {
    if (state == ST_ENABLED) {
      for (uint8_t i = 0; i < NUM_SERVOS; i++) targetAngle[i] = HOME_ANGLE[i];
      lastPacketMs = millis();
      Serial.println("OK HOME");
    } else {
      Serial.println("ERR NOT_ENABLED");
    }
  } else if (!strcmp(line, "STATUS")) {
    printStatus();
  } else {
    int angles[NUM_SERVOS];
    if (!parseAngles(line, angles)) {
      invalidCount++;
      reportError("BAD_PACKET");
      return;
    }
    lastPacketMs = millis();                      // a valid packet is also a heartbeat
    if (state == ST_SAFE_HOLD) {                  // link is back: resume (slew-limited)
      state = ST_ENABLED;
      Serial.println("OK LINK_RESTORED");
    }
    if (state == ST_ENABLED) {
      for (uint8_t i = 0; i < NUM_SERVOS; i++)
        targetAngle[i] = constrain(angles[i], MIN_ANGLE[i], MAX_ANGLE[i]);
    }                                             // DISABLED / ESTOP: valid but ignored
  }
}

void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (!lineOverflow) { lineBuf[lineLen] = '\0'; handleLine(lineBuf); }
      else { invalidCount++; reportError("LINE_TOO_LONG"); }
      lineLen = 0; lineOverflow = false;
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      lineOverflow = true;
    }
  }
}

// ---------------------------------------------------------------- servo output
void updateServos(float dt) {
  if (!outputsActive || outputsReleased) return;
  float maxStep = MAX_SLEW_DEG_PER_SEC * dt;
  for (uint8_t i = 0; i < NUM_SERVOS; i++) {
    float diff = targetAngle[i] - currentAngle[i];
    if (diff >  maxStep) diff =  maxStep;
    if (diff < -maxStep) diff = -maxStep;
    currentAngle[i] += diff;
    float safe = constrain(currentAngle[i], (float)MIN_ANGLE[i], (float)MAX_ANGLE[i]);
    int ticks = angleToTicks(safe);
    if (ticks != lastTicks[i]) {
      pwm.setPWM(i, 0, ticks);
      lastTicks[i] = ticks;
    }
  }
}

// ---------------------------------------------------------------- Arduino entry points
void setup() {
  Serial.begin(SERIAL_BAUD);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);
  pwm.begin();                                    // PCA9685 resets with all outputs OFF -> no pulses
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(50);                             // 50 Hz servo frame
  for (uint8_t i = 0; i < NUM_SERVOS; i++) {
    currentAngle[i] = HOME_ANGLE[i];              // internal safe/home values; NOT written to servos yet
    targetAngle[i]  = HOME_ANGLE[i];
    lastTicks[i]    = -1;
  }
  lastPacketMs = lastUpdateMs = lastStatusMs = millis();
  Serial.println("HANDSYNC_ESP32 READY (state DISABLED - waiting for ENABLE)");
}

void loop() {
  readSerial();
  uint32_t now = millis();

  if (state == ST_ENABLED && (now - lastPacketMs) > COMMAND_TIMEOUT_MS) {
    state = ST_SAFE_HOLD;                         // stale command protection
    freezeAtCurrent();
    Serial.println("WARN TIMEOUT_SAFE_HOLD");
  }

  if (now - lastUpdateMs >= UPDATE_INTERVAL_MS) {
    float dt = (now - lastUpdateMs) / 1000.0f;
    lastUpdateMs = now;
    updateServos(dt);
  }

  if (now - lastStatusMs >= STATUS_INTERVAL_MS) {
    lastStatusMs = now;
    printStatus();
  }
}
