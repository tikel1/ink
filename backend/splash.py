"""Onboarding / pairing screens for unpaired frames.

Composed PORTRAIT (480x800), Ink-branded, then rotated into the 800x480 panel so
they read upright on a portrait-mounted frame. Output is 8-bit grayscale PNG —
ESPHome's online_image decoder is unreliable with 1-bit PNGs.
"""
from __future__ import annotations

import io
import os

import qrcode
from PIL import Image, ImageDraw, ImageFont

# Portrait composition size (rotated to the panel at the end).
PW, PH = 480, 800
_MARGIN = 40

# The Ink brand display face (Fraunces). Rendered with the variable font's
# weight + optical-size axes so the splashes match the app, not PIL's bitmap
# default. Falls back gracefully if the asset is missing.
_FONT_PATH = os.path.join(os.path.dirname(__file__), "assets", "fraunces.ttf")


def _font(size: int, weight: int = 600):
    try:
        f = ImageFont.truetype(_FONT_PATH, size)
        try:
            f.set_variation_by_axes([max(9, min(144, size)), weight, 0, 0])
        except Exception:  # noqa: BLE001 — non-variable build; use as-is
            pass
        return f
    except Exception:  # noqa: BLE001 — asset missing; legible fallback
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def _portrait():
    img = Image.new("L", (PW, PH), color=255)
    return img, ImageDraw.Draw(img)


def _center_text(draw, y, text, size, fill=0, weight=600):
    f = _font(size, weight)
    w = draw.textlength(text, font=f)
    draw.text(((PW - w) / 2, y), text, font=f, fill=fill)
    return y + size


# The Ink mark — the biomorphic blob from static/icon.svg, as cubic-bezier
# control points in the SVG's 512x512 viewBox. Each tuple is (cp1, cp2, end);
# the segment starts at the previous end (first starts at _BLOB_START). 'S'
# (smooth) control points are pre-reflected here so we only handle plain cubics.
_BLOB_START = (258, 104)
_BLOB = [
    ((338, 98), (398, 138), (408, 214)),
    ((418, 290), (372, 332), (392, 366)),
    ((412, 400), (320, 412), (250, 410)),
    ((180, 408), (150, 398), (120, 338)),
    ((90, 278), (92, 206), (122, 168)),
    ((152, 130), (196, 110), (258, 104)),
]


def _ink_mark(draw, cx, cy, size: int = 86):
    """Render the Ink icon blob (filled black), scaled to `size` px and centered
    at (cx, cy). Flattens the bezier path to a polygon — no SVG lib needed."""
    pts = []
    p0 = _BLOB_START
    for p1, p2, p3 in _BLOB:
        for i in range(1, 21):
            t = i / 20.0
            mt = 1 - t
            a, b, c, d = mt * mt * mt, 3 * mt * mt * t, 3 * mt * t * t, t * t * t
            pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
        p0 = p3
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    scale = size / max(max(xs) - min(xs), max(ys) - min(ys))
    bcx, bcy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    draw.polygon([((x - bcx) * scale + cx, (y - bcy) * scale + cy) for x, y in pts], fill=0)


def _qr(data: str, box: int = 5) -> Image.Image:
    qr = qrcode.QRCode(box_size=box, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("L")


def _finish(img: Image.Image) -> bytes:
    """Rotate portrait composition into the 800x480 panel; emit 8-bit PNG."""
    panel = img.rotate(90, expand=True)        # -> 800x480, upright when portrait-mounted
    out = io.BytesIO()
    panel.save(out, format="PNG")
    return out.getvalue()


def _masthead(draw):
    _ink_mark(draw, PW // 2, 92)
    _center_text(draw, 144, "Ink", 72, weight=900)
    draw.line((_MARGIN, 238, PW - _MARGIN, 238), fill=0, width=3)


# --------------------------------------------------------------------------- #
def onboarding_splash(app_url: str, ap_name: str) -> bytes:
    """Stage A — no WiFi yet: how to install the app + join the frame's WiFi."""
    img, draw = _portrait()
    _masthead(draw)
    _center_text(draw, 262, "Let's get started", 30, weight=600)
    qr = _qr(app_url, box=5)
    img.paste(qr, ((PW - qr.width) // 2, 320))
    y = 320 + qr.height + 16
    _center_text(draw, y, "1.  Scan to get the Ink app", 22, weight=450)
    _center_text(draw, y + 34, f"2.  Join Wi-Fi “{ap_name}”", 22, weight=450)
    _center_text(draw, y + 68, "3.  Pick your home Wi-Fi", 22, weight=450)
    return _finish(img)


def pairing_splash(code: str, pair_url: str) -> bytes:
    """Stage B — on WiFi, not paired: pairing code + QR to scan in the app."""
    img, draw = _portrait()
    _masthead(draw)
    _center_text(draw, 262, "Pair your frame", 30, weight=600)
    qr = _qr(pair_url, box=6)
    img.paste(qr, ((PW - qr.width) // 2, 312))
    y = 312 + qr.height + 18
    _center_text(draw, y, "Scan this with the Ink app", 22, weight=450)
    _center_text(draw, y + 40, "Pairing code", 20, weight=500)
    _center_text(draw, y + 68, code, 60, weight=800)
    return _finish(img)


def connect_splash(ap_name: str) -> bytes:
    """Paired but no artwork yet — prompt the user to generate the first one."""
    img, draw = _portrait()
    _masthead(draw)
    _center_text(draw, 300, "Pairing successful", 32, weight=600)
    _center_text(draw, 372, "Open the Ink app and tap", 24, weight=450)
    _center_text(draw, 404, "Generate to create your", 24, weight=450)
    _center_text(draw, 436, "first artwork.", 24, weight=450)
    return _finish(img)


def updating_splash() -> bytes:
    """Shown on the frame while a firmware update downloads + installs."""
    img, draw = _portrait()
    _masthead(draw)
    _center_text(draw, 320, "Updating", 34, weight=600)
    _center_text(draw, 392, "Installing the latest firmware.", 22, weight=450)
    _center_text(draw, 426, "This takes about a minute —", 22, weight=450)
    _center_text(draw, 458, "keep the frame plugged in.", 22, weight=450)
    return _finish(img)
