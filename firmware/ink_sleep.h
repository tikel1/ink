#pragma once
// Multi-button deep-sleep wake for Ink: wake when EITHER KEY1 (GPIO2) or
// KEY3 (GPIO5) is pressed (both are active-low with pull-ups). Uses the RTC
// ext1 wake source so it works alongside the timer wake configured by ESPHome's
// deep_sleep component (the timer is the guaranteed fallback).
#include "esp_sleep.h"
#include "driver/rtc_io.h"
#include "esp_task_wdt.h"

// A blocking image fetch to a dead/slow/asleep server can stall the main loop.
// The default 5s task watchdog then reboots the frame, looping forever while the
// backend is unreachable. Relax it to 30s at runtime (no IDF rebuild needed) so
// an unreachable server just means "no new art", never a reboot loop.
inline void ink_relax_watchdog() {
  esp_task_wdt_config_t cfg = {};
  cfg.timeout_ms = 30000;
  cfg.idle_core_mask = 0x3;   // keep both idle cores watched
  cfg.trigger_panic = true;
  esp_task_wdt_reconfigure(&cfg);
}

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
