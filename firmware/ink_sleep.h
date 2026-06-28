#pragma once
// Multi-button deep-sleep wake for Ink: wake when EITHER KEY1 (GPIO2) or
// KEY3 (GPIO5) is pressed (both are active-low with pull-ups). Uses the RTC
// ext1 wake source so it works alongside the timer wake configured by ESPHome's
// deep_sleep component (the timer is the guaranteed fallback).
#include "esp_sleep.h"
#include "driver/rtc_io.h"

static const uint64_t INK_WAKE_MASK = (1ULL << 2) | (1ULL << 5);  // GPIO2 | GPIO5

inline void ink_enable_button_wakeup() {
  // Hold the internal pull-ups in the RTC domain so the pins read high while
  // asleep and a press (low) triggers the wake.
  rtc_gpio_pullup_en(GPIO_NUM_2);
  rtc_gpio_pulldown_dis(GPIO_NUM_2);
  rtc_gpio_pullup_en(GPIO_NUM_5);
  rtc_gpio_pulldown_dis(GPIO_NUM_5);
  esp_sleep_enable_ext1_wakeup(INK_WAKE_MASK, ESP_EXT1_WAKEUP_ANY_LOW);
}
