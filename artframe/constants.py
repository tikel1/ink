"""Shared constants — no magic values scattered across the codebase."""
from __future__ import annotations

# E-ink panel geometry (Seeed TRMNL 7.5", landscape).
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

# Time math.
SECONDS_PER_DAY = 86_400
SECONDS_PER_HOUR = 3_600

# Device fetch cadence bounds (seconds). The firmware sleeps for `refresh_rate`
# seconds; we clamp so a misconfigured wake time can never brick the cadence.
MIN_REFRESH_SECONDS = 5 * 60
MAX_REFRESH_SECONDS = SECONDS_PER_DAY

# Pairing code: 6 digits, never starts with 0 so it always renders 6 glyphs.
PAIRING_CODE_MIN = 100_000
PAIRING_CODE_MAX = 999_999

# Device lifecycle states.
STATUS_UNPAIRED = "unpaired"
STATUS_PAIRED = "paired"

# Daily artwork generation states.
ARTWORK_PENDING = "pending"
ARTWORK_READY = "ready"
ARTWORK_FAILED = "failed"

# Supported languages for event narration text.
LANGUAGES = ("en", "he")

# Temperature units.
TEMP_UNITS = ("c", "f")

# Holiday source toggles.
HOLIDAY_SOURCES = ("jewish", "israeli", "global")
