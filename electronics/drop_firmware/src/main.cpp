// Trash drop mechanism: 4x RDS3115 servos + ACS712 30A current sensor.
//
// Serial commands (115200, newline-terminated):
//   <ID> <angle>   move servo ID (FR, FL, BR, BL) to angle 0-180, e.g. "FR 90"
//   ALL <angle>    move all servos
//   LEFT <angle>   move FL and BL
//   RIGHT <angle>  move FR and BR
//   OPEN           move every servo to its open angle
//   CLOSE          move every servo to its close angle
//   OFF            stop PWM on all servos (they go limp)
//
// All moves are eased ramps at SERVO_SPEED_DEG_PER_S, except the overload
// OPEN, which jumps at the servos' full speed. Servos moved by one
// command start and finish together.
//
// Safety:
//   - The first PWM a servo gets is its close angle (or, after a reset that
//     was not a power-on, the position it was at before the reset), so it
//     doesn't jump to some default angle.
//   - Servos are attached one at a time, so they don't all jerk at once.
//   - Angles outside each servo's close..open range (+ LIMIT_MARGIN_DEG) are
//     rejected.
//
// Overload: if the servo current stays above a threshold for
// OVERLOAD_CONFIRM_MS, the doors OPEN (dropping the load), stay open 2 s and
// CLOSE again (opening at full speed, closing smoothly). It works at any moment, also during a move. The threshold is
// OVERLOAD_HOLD_A while the servos are still, and the higher
// OVERLOAD_MOVING_A while they move or settle (normal moves draw ~0.5 A).
//
// On boot runs OPEN, then CLOSE after 2 s; any serial command cancels that.
// Every 100 ms prints the average of the last 20 current sensor readings.

#include <Arduino.h>
#include <math.h>

// ---- Servos ----------------------------------------------------------------

struct Servo {
  const char *id;
  uint8_t pin;
  uint8_t channel;
  int closeAngle;
  int openAngle;
  bool attached;
  // Motion state: pos is the angle currently sent to the servo.
  float pos;
  float moveFrom;
  float moveTo;
  uint32_t moveStartMs;
  uint32_t moveDurationMs;
};

// Tune closeAngle / openAngle per servo with "<ID> <angle>", then copy the
// values here.
Servo servos[] = {
    // id   pin ch  close open
    {"FR", 5, 0, 15, 80, false},   // front right
    {"FL", 6, 1, 100, 35, false},  // front left
    {"BR", 7, 2, 100, 35, false},  // back right
    {"BL", 10, 3, 15, 82, false},  // back left
};
const size_t SERVO_COUNT = sizeof(servos) / sizeof(servos[0]);

const uint32_t PWM_FREQ_HZ = 50;
const uint8_t PWM_RESOLUTION_BITS = 14;
const uint32_t PWM_PERIOD_US = 1000000 / PWM_FREQ_HZ;
const float PULSE_MIN_US = 500;   // 0 deg
const float PULSE_MAX_US = 2500;  // 180 deg

const float SERVO_SPEED_DEG_PER_S = 40;  // average speed of a move
const uint32_t SERVO_UPDATE_MS = 20;     // one PWM period
const uint32_t ATTACH_STAGGER_MS = 300;  // pause between attaching servos at boot
const int LIMIT_MARGIN_DEG = 10;         // allowed overshoot past close/open

// Last positions, kept in RTC memory across resets that are not power-on
// (reset button, flashing, crash), so the servos don't jump on reboot.
const uint32_t SAVED_MAGIC = 0xD70F5E7A;
RTC_NOINIT_ATTR uint32_t savedMagic;
RTC_NOINIT_ATTR float savedPos[SERVO_COUNT];

int minAngle(const Servo &s) { return max(0, min(s.closeAngle, s.openAngle) - LIMIT_MARGIN_DEG); }
int maxAngle(const Servo &s) { return min(180, max(s.closeAngle, s.openAngle) + LIMIT_MARGIN_DEG); }

void servoOutput(Servo &s) {
  float pulseUs = PULSE_MIN_US + (PULSE_MAX_US - PULSE_MIN_US) * s.pos / 180.0f;
  uint32_t duty = pulseUs * ((1 << PWM_RESOLUTION_BITS) - 1) / PWM_PERIOD_US;
  ledcWrite(s.channel, duty);
}

void servoAttach(Servo &s) {
  if (s.attached) return;
  // Set the duty before connecting the pin, so the first pulse is already
  // the current position.
  ledcSetup(s.channel, PWM_FREQ_HZ, PWM_RESOLUTION_BITS);
  servoOutput(s);
  ledcAttachPin(s.pin, s.channel);
  s.attached = true;
}

void servoDetach(Servo &s) {
  if (!s.attached) return;
  ledcDetachPin(s.pin);
  digitalWrite(s.pin, LOW);
  s.attached = false;
  s.moveDurationMs = 0;
}

bool servoMoving(const Servo &s) { return s.moveDurationMs > 0; }

// Moves the servos that have a non-NAN target; they all take the time the
// longest move needs, so they finish together. fast skips the ramp: the
// servos get the target at once and move at their own full speed.
void moveServos(const float targets[], bool fast = false) {
  float maxDelta = 0;
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    if (!isnan(targets[i])) maxDelta = max(maxDelta, fabsf(targets[i] - servos[i].pos));
  }
  uint32_t duration =
      fast ? SERVO_UPDATE_MS
           : max<uint32_t>(SERVO_UPDATE_MS, maxDelta / SERVO_SPEED_DEG_PER_S * 1000);
  uint32_t now = millis();
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    if (isnan(targets[i])) continue;
    Servo &s = servos[i];
    servoAttach(s);
    s.moveFrom = s.pos;
    s.moveTo = targets[i];
    s.moveStartMs = now;
    s.moveDurationMs = duration;
  }
}

uint32_t lastMotionMs = 0;  // last time any servo was moving

void updateServos() {
  uint32_t now = millis();
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    Servo &s = servos[i];
    if (servoMoving(s)) {
      lastMotionMs = now;
      float t = (float)(now - s.moveStartMs) / s.moveDurationMs;
      if (t >= 1) {
        s.pos = s.moveTo;
        s.moveDurationMs = 0;
      } else {
        float eased = t * t * (3 - 2 * t);  // smoothstep: slow start and stop
        s.pos = s.moveFrom + (s.moveTo - s.moveFrom) * eased;
      }
      servoOutput(s);
    }
    savedPos[i] = s.pos;
  }
}

bool anyServoMoving() {
  for (Servo &s : servos) {
    if (servoMoving(s)) return true;
  }
  return false;
}

// Groups of servos addressed by one command. Members are matched by the
// side letter, the second character of the servo ID (FL -> 'L').
struct Group {
  const char *id;
  char side;  // 'L', 'R', or 0 for all
};

Group groups[] = {
    {"ALL", 0},
    {"LEFT", 'L'},
    {"RIGHT", 'R'},
};

Group *findGroup(const String &id) {
  for (Group &g : groups) {
    if (id.equalsIgnoreCase(g.id)) return &g;
  }
  return nullptr;
}

Servo *findServo(const String &id) {
  for (Servo &s : servos) {
    if (id.equalsIgnoreCase(s.id)) return &s;
  }
  return nullptr;
}

// ---- Current sensor (ACS712 30A) -------------------------------------------

const uint8_t CURRENT_PIN = 3;
const int CURRENT_ADC_SAMPLES = 8;  // ADC reads per reading
const int CURRENT_AVG_READINGS = 20;
const uint32_t CURRENT_SAMPLE_MS = 5;  // 20 readings span 100 ms
// ACS712 OUT reaches GPIO3 through the R1 10k / R2 15k divider.
const float DIVIDER_RATIO = 15.0f / (10.0f + 15.0f);
// Sensitivity is 66 mV/A at VCC = 5V, i.e. 0.0132 * VCC per amp. At the
// zero point the pin sees VCC / 2 * ratio, so the sensitivity at the pin is
// 0.0264 * zero mV per amp (independent of the real VCC and divider ratio).
const float SENSITIVITY_PER_ZERO_MV = 0.0264f;
// The ACS712 is wired with IP+ and IP- swapped, so servo current reads
// negative. Set to 1 if the power wires on it are swapped back.
const float CURRENT_SIGN = -1;
const uint32_t REPORT_INTERVAL_MS = 100;

float currentZeroMv = 0;
float currentReadings[CURRENT_AVG_READINGS];
int currentReadingCount = 0;
int currentReadingIndex = 0;

float readCurrentPinMv() {
  uint32_t sum = 0;
  for (int i = 0; i < CURRENT_ADC_SAMPLES; i++) {
    sum += analogReadMilliVolts(CURRENT_PIN);
  }
  return (float)sum / CURRENT_ADC_SAMPLES;
}

void calibrateCurrentZero() {
  // Servos have no PWM yet, so they draw (almost) nothing.
  float sum = 0;
  const int rounds = 64;
  for (int i = 0; i < rounds; i++) {
    sum += readCurrentPinMv();
    delay(2);
  }
  currentZeroMv = sum / rounds;
}

void sampleCurrent() {
  currentReadings[currentReadingIndex] = readCurrentPinMv();
  currentReadingIndex = (currentReadingIndex + 1) % CURRENT_AVG_READINGS;
  if (currentReadingCount < CURRENT_AVG_READINGS) currentReadingCount++;
}

float averagePinMv() {
  float sum = 0;
  for (int i = 0; i < currentReadingCount; i++) sum += currentReadings[i];
  return sum / currentReadingCount;
}

float pinMvToAmps(float pinMv) {
  return CURRENT_SIGN * (pinMv - currentZeroMv) / (SENSITIVITY_PER_ZERO_MV * currentZeroMv);
}

void reportCurrent() {
  if (currentReadingCount == 0) return;
  float pinMv = averagePinMv();
  float sensorMv = pinMv / DIVIDER_RATIO;
  float amps = pinMvToAmps(pinMv);
  Serial.printf("[current] pin=%.1f mV sensor_out=%.1f mV zero=%.1f mV I=%.3f A\n",
                pinMv, sensorMv, currentZeroMv, amps);
}

void moveOpenClose(bool open, bool fast = false) {
  float targets[SERVO_COUNT];
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    targets[i] = open ? servos[i].openAngle : servos[i].closeAngle;
    Serial.printf("[ok] %s -> %d deg\n", servos[i].id, (int)targets[i]);
  }
  moveServos(targets, fast);
  Serial.printf("[ok] %s%s\n", open ? "OPEN" : "CLOSE", fast ? " (full speed)" : "");
}

// ---- Startup sequence ------------------------------------------------------

enum StartupStage { STARTUP_OPENING, STARTUP_WAITING, STARTUP_CLOSING, STARTUP_DONE };
StartupStage startupStage = STARTUP_DONE;
uint32_t startupWaitStartMs = 0;
const uint32_t STARTUP_OPEN_HOLD_MS = 2000;

void handleCommand(String line);

void updateStartup() {
  switch (startupStage) {
    case STARTUP_OPENING:
      if (!anyServoMoving()) {
        startupStage = STARTUP_WAITING;
        startupWaitStartMs = millis();
      }
      break;
    case STARTUP_WAITING:
      if (millis() - startupWaitStartMs >= STARTUP_OPEN_HOLD_MS) {
        handleCommand("CLOSE");
        startupStage = STARTUP_CLOSING;
      }
      break;
    case STARTUP_CLOSING:
      if (!anyServoMoving()) {
        Serial.println("[ok] startup sequence done");
        startupStage = STARTUP_DONE;
      }
      break;
    case STARTUP_DONE:
      break;
  }
}

// ---- Overload --------------------------------------------------------------

// Measured: empty closed doors hold at ~0.05 A, loaded ones at 0.14-0.18 A;
// moves draw up to ~0.5 A and the current settles ~1 s after a move ends.
const float OVERLOAD_HOLD_A = 0.10;
const float OVERLOAD_MOVING_A = 0.70;
const uint32_t OVERLOAD_SETTLE_MS = 1200;   // after a move, still use the moving threshold
const uint32_t OVERLOAD_CONFIRM_MS = 300;   // current must stay high this long
const uint32_t OVERLOAD_OPEN_HOLD_MS = 2000;

enum OverloadStage { OVERLOAD_WATCHING, OVERLOAD_OPENING, OVERLOAD_WAITING };
OverloadStage overloadStage = OVERLOAD_WATCHING;
uint32_t overloadSinceMs = 0;  // 0 = current is below the threshold
uint32_t overloadWaitStartMs = 0;

void updateOverload() {
  uint32_t now = millis();
  switch (overloadStage) {
    case OVERLOAD_WATCHING: {
      bool anyAttached = false;
      for (Servo &s : servos) anyAttached |= s.attached;
      if (!anyAttached || currentReadingCount == 0) {
        overloadSinceMs = 0;
        return;
      }
      bool settling = anyServoMoving() || now - lastMotionMs < OVERLOAD_SETTLE_MS;
      float limit = settling ? OVERLOAD_MOVING_A : OVERLOAD_HOLD_A;
      float amps = pinMvToAmps(averagePinMv());
      if (amps <= limit) {
        overloadSinceMs = 0;
        return;
      }
      if (overloadSinceMs == 0) overloadSinceMs = now;
      if (now - overloadSinceMs < OVERLOAD_CONFIRM_MS) return;

      Serial.printf("[overload] I=%.3f A > %.2f A (%s) -> OPEN for %lu ms, then CLOSE\n", amps,
                    limit, settling ? "moving" : "holding", OVERLOAD_OPEN_HOLD_MS);
      startupStage = STARTUP_DONE;
      moveOpenClose(true, true);
      overloadStage = OVERLOAD_OPENING;
      overloadSinceMs = 0;
      break;
    }
    case OVERLOAD_OPENING:
      if (!anyServoMoving()) {
        overloadStage = OVERLOAD_WAITING;
        overloadWaitStartMs = now;
      }
      break;
    case OVERLOAD_WAITING:
      if (now - overloadWaitStartMs >= OVERLOAD_OPEN_HOLD_MS) {
        handleCommand("CLOSE");
        overloadStage = OVERLOAD_WATCHING;  // also watches the closing move
      }
      break;
  }
}

// ---- Serial commands -------------------------------------------------------

String lineBuffer;

void handleCommand(String line) {
  line.trim();
  if (line.isEmpty()) return;

  int space = line.indexOf(' ');
  String id = space < 0 ? line : line.substring(0, space);
  String arg = space < 0 ? "" : line.substring(space + 1);
  arg.trim();

  float targets[SERVO_COUNT];
  for (float &t : targets) t = NAN;

  if (id.equalsIgnoreCase("OFF")) {
    for (Servo &s : servos) servoDetach(s);
    overloadStage = OVERLOAD_WATCHING;  // don't re-attach them to CLOSE
    Serial.println("[ok] all servos off");
    return;
  }

  if (id.equalsIgnoreCase("OPEN") || id.equalsIgnoreCase("CLOSE")) {
    moveOpenClose(id.equalsIgnoreCase("OPEN"));
    return;
  }

  if (arg.isEmpty()) {
    Serial.println("[err] usage: <FR|FL|BR|BL|LEFT|RIGHT|ALL> <0-180>, OPEN, CLOSE or OFF");
    return;
  }
  char *end;
  long angle = strtol(arg.c_str(), &end, 10);
  if (*end != '\0' || angle < 0 || angle > 180) {
    Serial.printf("[err] bad angle '%s', expected 0-180\n", arg.c_str());
    return;
  }

  Group *g = findGroup(id);
  Servo *single = g ? nullptr : findServo(id);
  if (!g && !single) {
    Serial.printf("[err] unknown servo '%s', expected FR, FL, BR, BL, LEFT, RIGHT or ALL\n",
                  id.c_str());
    return;
  }

  for (size_t i = 0; i < SERVO_COUNT; i++) {
    Servo &s = servos[i];
    bool selected = single ? &s == single : (g->side == 0 || s.id[1] == g->side);
    if (!selected) continue;
    if (angle < minAngle(s) || angle > maxAngle(s)) {
      Serial.printf("[err] %s: %ld deg is outside its safe range %d-%d, nothing moved\n", s.id,
                    angle, minAngle(s), maxAngle(s));
      return;
    }
    targets[i] = angle;
  }
  moveServos(targets);
  Serial.printf("[ok] %s -> %ld deg\n", g ? g->id : single->id, angle);
}

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (!lineBuffer.isEmpty()) startupStage = STARTUP_DONE;  // user takes over
      handleCommand(lineBuffer);
      lineBuffer = "";
    } else if (lineBuffer.length() < 32) {
      lineBuffer += c;
    }
  }
}

// ---- Main ------------------------------------------------------------------

void setup() {
  // Hold the signal lines low until PWM starts: no pulses means the servos
  // stay where they are.
  for (Servo &s : servos) {
    pinMode(s.pin, OUTPUT);
    digitalWrite(s.pin, LOW);
  }

  // Start from the close angle, or from the remembered position if the chip
  // was reset without losing power.
  esp_reset_reason_t reason = esp_reset_reason();
  bool restored = savedMagic == SAVED_MAGIC && reason != ESP_RST_POWERON &&
                  reason != ESP_RST_BROWNOUT;
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    Servo &s = servos[i];
    bool valid = restored && savedPos[i] >= minAngle(s) && savedPos[i] <= maxAngle(s);
    s.pos = valid ? savedPos[i] : s.closeAngle;
    savedPos[i] = s.pos;
  }
  savedMagic = SAVED_MAGIC;

  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(CURRENT_PIN, ADC_11db);

  // Give the USB CDC a moment so the first lines aren't lost.
  delay(1500);
  calibrateCurrentZero();

  Serial.println("Drop mechanism ready.");
  Serial.println("Commands: <FR|FL|BR|BL|LEFT|RIGHT|ALL> <0-180>, OPEN, CLOSE, OFF");
  Serial.printf("Current sensor zero: %.1f mV\n", currentZeroMv);
  Serial.printf("Start positions (%s):", restored ? "restored after reset" : "close angles");
  for (Servo &s : servos) Serial.printf(" %s=%.0f", s.id, s.pos);
  Serial.println();

  for (Servo &s : servos) {
    servoAttach(s);
    delay(ATTACH_STAGGER_MS);
  }

  // Startup self-test: open, then close.
  handleCommand("OPEN");
  startupStage = STARTUP_OPENING;
}

void loop() {
  pollSerial();

  uint32_t now = millis();

  static uint32_t lastServoUpdate = 0;
  if (now - lastServoUpdate >= SERVO_UPDATE_MS) {
    lastServoUpdate = now;
    updateServos();
    updateStartup();
    updateOverload();
  }

  static uint32_t lastSample = 0;
  if (now - lastSample >= CURRENT_SAMPLE_MS) {
    lastSample = now;
    sampleCurrent();
  }

  static uint32_t lastReport = 0;
  if (now - lastReport >= REPORT_INTERVAL_MS) {
    lastReport = now;
    reportCurrent();
  }
}
