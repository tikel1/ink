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

# Frame orientation (affects composition, generation size, and panel rotation).
ORIENTATIONS = ("landscape", "portrait")

# Date embedded in the artwork. The stored value is a token format string
# (ddd/dddd/MMM/MMMM/MM/D/Do/DD/YYYY/YY + literal separators), so the user can pick
# a preset or type a custom format. Legacy enum keys are mapped for back-compat.
import re as _re

_LEGACY_DATE_FORMATS = {
    "weekday":   "ddd, MMM DD",    # Sun, Jun 28
    "month_day": "MMMM DD",        # June 28
    "abbr_year": "MMM DD, YYYY",   # Jun 28, 2026
    "dmy":       "DD/MM/YYYY",     # 28/06/2026
    "mdy":       "MM/DD/YYYY",     # 06/28/2026
}
DEFAULT_DATE_FORMAT = "weekday"
MAX_DATE_FORMAT_LEN = 40

_DATE_TOKEN = _re.compile(r"dddd|ddd|MMMM|MMM|MM|YYYY|YY|DD|Do|D")


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def format_date(dt, fmt: str) -> str:
    """Render `dt` with a token format string. Tokens: dddd (Tuesday), ddd (Tue),
    MMMM (June), MMM (Jun), MM (06), DD (30), D (30), Do (30th), YYYY (2026),
    YY (26). Legacy enum keys map to their original layout first. Unknown letters
    pass through literally, so a custom string renders exactly as typed."""
    fmt = _LEGACY_DATE_FORMATS.get(fmt, fmt or _LEGACY_DATE_FORMATS[DEFAULT_DATE_FORMAT])
    tokens = {
        "dddd": dt.strftime("%A"), "ddd": dt.strftime("%a"),
        "MMMM": dt.strftime("%B"), "MMM": dt.strftime("%b"),
        "MM": f"{dt.month:02d}", "DD": f"{dt.day:02d}",
        "Do": _ordinal(dt.day), "D": str(dt.day),
        "YYYY": str(dt.year), "YY": f"{dt.year % 100:02d}",
    }
    return _DATE_TOKEN.sub(lambda m: tokens[m.group(0)], fmt)

# Curated interest fields offered in the app (plus free-text "other").
INTEREST_FIELDS = ("science", "history", "sports", "astronomy", "art")

# Holiday source toggles.
HOLIDAY_SOURCES = ("jewish", "israeli", "global")
