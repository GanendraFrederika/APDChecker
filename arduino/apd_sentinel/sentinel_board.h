#ifndef SENTINEL_BOARD_H
#define SENTINEL_BOARD_H
// Board-level types for apd_sentinel.ino. They live in a header because the
// Arduino .ino preprocessor emits function prototypes before any type that is
// declared inside the sketch itself.
#include <stdint.h>

struct OneWirePin {
  volatile uint8_t *mode, *out, *in;
  uint8_t mask;
  int16_t lastDc;
  bool present;
};

struct ToneStep {
  uint16_t hz;
  uint16_t ms;
};

#endif
