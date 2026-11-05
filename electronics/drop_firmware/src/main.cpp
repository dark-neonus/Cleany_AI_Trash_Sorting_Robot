// Trash drop mechanism: 4x RDS3115 servos + ACS712 30A current sensor.
//
// Serial protocol (115200, one command per line, one reply line per command):
//   OPEN       drop: open at full speed, stay open DROP_OPEN_MS, close smoothly
//   OPEN_HOLD  open smoothly and stay open
//   CLOSE      close smoothly and stay closed
//   STOP       freeze the servos where they are now
//   READ       "R I=<mA> MAX=<mA|-> S=<state> FR=<deg> FL=<deg> BR=<deg> BL=<deg>"
//                I    filtered servo current
//                MAX  current that triggers a drop right now; "-" while overload
//                     detection is off (held open, stopped, during a drop)
//                S    OPEN, CLOSED, OPENING, CLOSING, STOPPED, PARTIAL or OFF
// Other commands reply "OK <command>" or "ERR <reason>". Nothing else is sent,
// except one "READY ..." line after boot.
//
// Built with DEBUG_COMMANDS=1 (env esp32c3_supermini_debug) it also accepts the
// tuning commands: "<FR|FL|BR|BL|LEFT|RIGHT|ALL> <angle>" and OFF (servos limp).
//
// Moves are eased ramps at SERVO_SPEED_DEG_PER_S, except the drop opening,
// which jumps at the servos' full speed. Servos moved by one command start and
// finish together.
//
// Current: the ADC samples GPIO3 by DMA at the C3's maximum rate. Every
// READING_SAMPLES samples (~2 ms) become one reading, and the filtered current
// is the mean of the last FILTER_WINDOW readings (~20 ms, one servo PWM period,
// so the servos' 50 Hz current pulses average out).
//
// Overload: if the filtered current stays above the limit for
// OVERLOAD_CONFIRM_MS, the doors drop (same as OPEN). The limit is
// OVERLOAD_HOLD_A while the servos are still and OVERLOAD_MOVING_A while they
// move or settle. Detection is off while the doors are held open, stopped or
// tuned by hand.
//
// Safety:
//   - The first PWM a servo gets is its close angle (or, after a reset that
//     was not a power-on, the position it was at before the reset).
//   - Servos are attached one at a time.
//   - Tuning angles outside each servo's close..open range (+ LIMIT_MARGIN_DEG)
//     are rejected.
//
// On boot runs a smooth OPEN, waits 2 s and CLOSEs; any motion command cancels it.

#include <Arduino.h>
#include <driver/adc.h>
#include <esp_adc_cal.h>
#include <math.h>

#ifndef DEBUG_COMMANDS
#define DEBUG_COMMANDS 0
#endif

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

// Tune closeAngle / openAngle per servo with the debug build's "<ID> <angle>",
// then copy the values here.
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

uint32_t lastMotionMs = 0;  // last time any servo was moving

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

bool anyServoMoving() {
  for (Servo &s : servos) {
    if (servoMoving(s)) return true;
  }
  return false;
}

bool anyServoAttached() {
  for (Servo &s : servos) {
    if (s.attached) return true;
  }
  return false;
}

// Moves the servos that have a non-NAN target; they all take the time the
// longest move needs, so they finish together. fast skips the ramp: the
// servos get the target at once and move at their own full speed.
void moveServos(const float targets[], bool fast = false) {
  float maxDelta = 0;
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    if (!isnan(targets[i])) maxDelta = max(maxDelta, fabsf(targets[i] - servos[i].pos));
  }
  uint32_t duration = max<uint32_t>(SERVO_UPDATE_MS, maxDelta / SERVO_SPEED_DEG_PER_S * 1000);
  uint32_t now = millis();
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    if (isnan(targets[i])) continue;
    Servo &s = servos[i];
    servoAttach(s);
    s.moveFrom = s.pos;
    s.moveTo = targets[i];
    s.moveStartMs = now;
    if (fast) {
      // Write now instead of on the next update tick: every ms counts here.
      s.pos = s.moveTo;
      s.moveDurationMs = 0;
      savedPos[i] = s.pos;
      servoOutput(s);
      lastMotionMs = now;
    } else {
      s.moveDurationMs = duration;
    }
  }
}

void moveOpenClose(bool open, bool fast = false) {
  float targets[SERVO_COUNT];
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    targets[i] = open ? servos[i].openAngle : servos[i].closeAngle;
  }
  moveServos(targets, fast);
}

void stopServos() {
  for (Servo &s : servos) s.moveDurationMs = 0;  // pos is what was last sent: hold it
}

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

// ---- Modes and the drop sequence -------------------------------------------

enum Mode {
  MODE_AUTO,       // closed or closing; overload detection on
  MODE_HOLD_OPEN,  // OPEN_HOLD
  MODE_STOPPED,    // STOP or OFF
  MODE_MANUAL,     // debug tuning commands
};
Mode mode = MODE_AUTO;

enum DropStage { DROP_IDLE, DROP_OPENING, DROP_WAITING };
DropStage dropStage = DROP_IDLE;
uint32_t dropWaitStartMs = 0;
const uint32_t DROP_OPEN_MS = 2000;

void startDrop(bool fast) {
  mode = MODE_AUTO;
  moveOpenClose(true, fast);
  dropStage = DROP_OPENING;
}

void updateDrop() {
  switch (dropStage) {
    case DROP_OPENING:
      if (!anyServoMoving()) {
        dropStage = DROP_WAITING;
        dropWaitStartMs = millis();
      }
      break;
    case DROP_WAITING:
      if (millis() - dropWaitStartMs >= DROP_OPEN_MS) {
        moveOpenClose(false);
        dropStage = DROP_IDLE;
      }
      break;
    case DROP_IDLE:
      break;
  }
}

// ---- Current sensor (ACS712 30A) -------------------------------------------

const adc1_channel_t CURRENT_CHANNEL = ADC1_CHANNEL_3;  // GPIO3
const uint32_t ADC_SAMPLE_HZ = SOC_ADC_SAMPLE_FREQ_THRES_HIGH;  // 83333, the C3 maximum
const uint32_t ADC_FRAME_BYTES = 256;  // 64 samples per DMA interrupt
const uint32_t READING_SAMPLES = ADC_SAMPLE_HZ / 500;  // one reading per ~2 ms
const int FILTER_WINDOW = 10;  // readings in the moving average (~20 ms)
// ACS712 OUT reaches GPIO3 through the R1 10k / R2 15k divider.
const float DIVIDER_RATIO = 15.0f / (10.0f + 15.0f);
// Sensitivity is 66 mV/A at VCC = 5V, i.e. 0.0132 * VCC per amp. At the
// zero point the pin sees VCC / 2 * ratio, so the sensitivity at the pin is
// 0.0264 * zero mV per amp (independent of the real VCC and divider ratio).
const float SENSITIVITY_PER_ZERO_MV = 0.0264f;
// The ACS712 is wired with IP+ and IP- swapped, so servo current reads
// negative. Set to 1 if the power wires on it are swapped back.
const float CURRENT_SIGN = -1;

esp_adc_cal_characteristics_t adcChars;
float currentZeroMv = 0;
uint32_t adcRateHz = 0;  // measured during the zero calibration

uint32_t readingSum = 0;
uint32_t readingCount = 0;
float window[FILTER_WINDOW];
float windowSum = 0;
int windowFill = 0;
int windowIndex = 0;
float currentAmps = 0;  // filtered

void adcStart() {
  adc_digi_init_config_t init = {};
  init.max_store_buf_size = ADC_FRAME_BYTES * 8;
  init.conv_num_each_intr = ADC_FRAME_BYTES;
  init.adc1_chan_mask = BIT(CURRENT_CHANNEL);
  init.adc2_chan_mask = 0;
  ESP_ERROR_CHECK(adc_digi_initialize(&init));

  adc_digi_pattern_config_t pattern = {};
  pattern.atten = ADC_ATTEN_DB_12;
  pattern.channel = CURRENT_CHANNEL;
  pattern.unit = 0;  // ADC1
  pattern.bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;

  adc_digi_configuration_t config = {};
  config.conv_limit_en = false;
  config.conv_limit_num = 250;
  config.pattern_num = 1;
  config.adc_pattern = &pattern;
  config.sample_freq_hz = ADC_SAMPLE_HZ;
  config.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  config.format = ADC_DIGI_OUTPUT_FORMAT_TYPE2;
  ESP_ERROR_CHECK(adc_digi_controller_configure(&config));

  esp_adc_cal_characterize(ADC_UNIT_1, ADC_ATTEN_DB_12, ADC_WIDTH_BIT_12, 0, &adcChars);
  ESP_ERROR_CHECK(adc_digi_start());
}

// Calls onSample(raw) for every GPIO3 sample the DMA has collected so far.
// Never blocks.
template <typename F>
void drainAdc(F onSample) {
  static uint8_t buf[ADC_FRAME_BYTES];
  while (true) {
    uint32_t len = 0;
    esp_err_t err = adc_digi_read_bytes(buf, sizeof buf, &len, 0);
    // ESP_ERR_INVALID_STATE: the DMA buffer overflowed, the data is still valid.
    if ((err != ESP_OK && err != ESP_ERR_INVALID_STATE) || len == 0) return;
    for (uint32_t i = 0; i + SOC_ADC_DIGI_DATA_BYTES_PER_CONV <= len;
         i += SOC_ADC_DIGI_DATA_BYTES_PER_CONV) {
      const adc_digi_output_data_t *d = (const adc_digi_output_data_t *)&buf[i];
      if (d->type2.unit == 0 && d->type2.channel == CURRENT_CHANNEL) onSample(d->type2.data);
    }
  }
}

// Calibrated mV for a fractional raw value (the calibration takes whole
// counts; one count is ~0.6 mV, ~15 mA, too coarse for averaged readings).
float rawToMv(float raw) {
  uint32_t lo = (uint32_t)raw;
  float vLo = esp_adc_cal_raw_to_voltage(lo, &adcChars);
  float vHi = esp_adc_cal_raw_to_voltage(lo + 1, &adcChars);
  return vLo + (vHi - vLo) * (raw - lo);
}

float mvToAmps(float pinMv) {
  return CURRENT_SIGN * (pinMv - currentZeroMv) / (SENSITIVITY_PER_ZERO_MV * currentZeroMv);
}

void calibrateCurrentZero() {
  // Servos have no PWM yet, so they draw (almost) nothing.
  const uint32_t durationMs = 250;
  uint64_t sum = 0;
  uint32_t count = 0;
  drainAdc([](uint16_t) {});  // drop samples from before this call
  uint32_t start = millis();
  while (millis() - start < durationMs) {
    drainAdc([&](uint16_t raw) {
      sum += raw;
      count++;
    });
  }
  currentZeroMv = rawToMv((float)sum / max<uint32_t>(count, 1));
  adcRateHz = count * 1000 / durationMs;
}

void checkOverload();

void pollCurrent() {
  drainAdc([](uint16_t raw) {
    readingSum += raw;
    if (++readingCount < READING_SAMPLES) return;
    float reading = mvToAmps(rawToMv((float)readingSum / readingCount));
    readingSum = 0;
    readingCount = 0;

    if (windowFill == FILTER_WINDOW) windowSum -= window[windowIndex];
    else windowFill++;
    window[windowIndex] = reading;
    windowSum += reading;
    windowIndex = (windowIndex + 1) % FILTER_WINDOW;
    currentAmps = windowSum / windowFill;

    checkOverload();
  });
}

// ---- Overload --------------------------------------------------------------

// Measured: empty closed doors hold at ~0.01-0.05 A, loaded ones at 0.14-0.18 A;
// moves draw up to ~0.5 A and the current settles ~1 s after a move ends.
const float OVERLOAD_HOLD_A = 0.10;
const float OVERLOAD_MOVING_A = 0.70;
const uint32_t OVERLOAD_SETTLE_MS = 1200;  // after a move, still use the moving limit
const uint32_t OVERLOAD_CONFIRM_MS = 30;   // current must stay above the limit this long

bool overloadHigh = false;
uint32_t overloadSinceMs = 0;

bool overloadArmed() { return mode == MODE_AUTO && dropStage == DROP_IDLE && anyServoAttached(); }

float overloadLimit() {
  bool settling = anyServoMoving() || millis() - lastMotionMs < OVERLOAD_SETTLE_MS;
  return settling ? OVERLOAD_MOVING_A : OVERLOAD_HOLD_A;
}

void checkOverload() {
  if (!overloadArmed() || currentAmps <= overloadLimit()) {
    overloadHigh = false;
    return;
  }
  uint32_t now = millis();
  if (!overloadHigh) {
    overloadHigh = true;
    overloadSinceMs = now;
  } else if (now - overloadSinceMs >= OVERLOAD_CONFIRM_MS) {
    overloadHigh = false;
    startDrop(true);
  }
}

// ---- READ ------------------------------------------------------------------

const char *doorState() {
  if (!anyServoAttached()) return "OFF";
  if (anyServoMoving()) {
    bool opening = true, closing = true;
    for (Servo &s : servos) {
      if (!servoMoving(s)) continue;
      opening &= s.moveTo == s.openAngle;
      closing &= s.moveTo == s.closeAngle;
    }
    return opening ? "OPENING" : closing ? "CLOSING" : "PARTIAL";
  }
  bool open = true, closed = true;
  for (Servo &s : servos) {
    open &= fabsf(s.pos - s.openAngle) < 0.5f;
    closed &= fabsf(s.pos - s.closeAngle) < 0.5f;
  }
  if (open) return "OPEN";
  if (closed) return "CLOSED";
  return mode == MODE_STOPPED ? "STOPPED" : "PARTIAL";
}

// One snprintf of integers and one write into the USB CDC buffer; the USB
// peripheral sends it from there.
void replyRead() {
  char maxStr[8] = "-";
  if (overloadArmed()) snprintf(maxStr, sizeof maxStr, "%d", (int)lroundf(overloadLimit() * 1000));
  char buf[96];
  int len = snprintf(buf, sizeof buf, "R I=%d MAX=%s S=%s", (int)lroundf(currentAmps * 1000),
                     maxStr, doorState());
  for (Servo &s : servos) {
    len += snprintf(buf + len, sizeof buf - len, " %s=%d", s.id, (int)lroundf(s.pos));
  }
  len += snprintf(buf + len, sizeof buf - len, "\n");
  Serial.write((const uint8_t *)buf, len);
}

// ---- Serial commands -------------------------------------------------------

#if DEBUG_COMMANDS
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

// "<ID|group> <angle>". Returns false if id is not a servo or group.
bool handleTuning(const String &id, const String &arg) {
  Group *g = findGroup(id);
  Servo *single = g ? nullptr : findServo(id);
  if (!g && !single) return false;

  char *end;
  long angle = strtol(arg.c_str(), &end, 10);
  if (arg.isEmpty() || *end != '\0' || angle < 0 || angle > 180) {
    Serial.printf("ERR bad angle '%s', expected 0-180\n", arg.c_str());
    return true;
  }
  float targets[SERVO_COUNT];
  for (size_t i = 0; i < SERVO_COUNT; i++) {
    Servo &s = servos[i];
    targets[i] = NAN;
    bool selected = single ? &s == single : (g->side == 0 || s.id[1] == g->side);
    if (!selected) continue;
    if (angle < minAngle(s) || angle > maxAngle(s)) {
      Serial.printf("ERR %s: %ld deg is outside its safe range %d-%d\n", s.id, angle, minAngle(s),
                    maxAngle(s));
      return true;
    }
    targets[i] = angle;
  }
  mode = MODE_MANUAL;
  dropStage = DROP_IDLE;
  moveServos(targets);
  Serial.printf("OK %s %ld\n", g ? g->id : single->id, angle);
  return true;
}
#endif

void handleCommand(String line) {
  line.trim();
  if (line.isEmpty()) return;
  int space = line.indexOf(' ');
  String cmd = space < 0 ? line : line.substring(0, space);
  String arg = space < 0 ? "" : line.substring(space + 1);
  arg.trim();
  cmd.toUpperCase();

  if (cmd == "READ") {
    replyRead();
    return;
  }
  if (cmd == "OPEN") {
    startDrop(true);
  } else if (cmd == "OPEN_HOLD") {
    mode = MODE_HOLD_OPEN;
    dropStage = DROP_IDLE;
    moveOpenClose(true);
  } else if (cmd == "CLOSE") {
    mode = MODE_AUTO;
    dropStage = DROP_IDLE;
    moveOpenClose(false);
  } else if (cmd == "STOP") {
    mode = MODE_STOPPED;
    dropStage = DROP_IDLE;
    stopServos();
#if DEBUG_COMMANDS
  } else if (cmd == "OFF") {
    for (Servo &s : servos) servoDetach(s);
    mode = MODE_STOPPED;
    dropStage = DROP_IDLE;
  } else if (handleTuning(cmd, arg)) {
    return;  // replied already
#endif
  } else {
    Serial.printf("ERR unknown command '%s'\n", line.c_str());
    return;
  }
  Serial.printf("OK %s\n", cmd.c_str());
}

String lineBuffer;

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
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
  Serial.setTxTimeoutMs(0);  // never block the loop when no host is reading

  adcStart();
  delay(300);  // let the ACS712 and the 5V settle before measuring its zero
  calibrateCurrentZero();

  Serial.printf("READY zero=%.1fmV adc=%luHz start=%s debug=%d\n", currentZeroMv,
                (unsigned long)adcRateHz, restored ? "restored" : "close", DEBUG_COMMANDS);

  for (Servo &s : servos) {
    servoAttach(s);
    delay(ATTACH_STAGGER_MS);
  }

  // Startup self-test: smooth open, 2 s, close.
  startDrop(false);
}

void loop() {
  pollSerial();
  pollCurrent();

  uint32_t now = millis();
  static uint32_t lastServoUpdate = 0;
  if (now - lastServoUpdate >= SERVO_UPDATE_MS) {
    lastServoUpdate = now;
    updateServos();
  }
  updateDrop();
}
