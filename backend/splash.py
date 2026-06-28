"""Onboarding / pairing screens for unpaired frames.

Composed PORTRAIT (480x800), Ink-branded, then rotated into the 800x480 panel so
they read upright on a portrait-mounted frame. Output is 8-bit grayscale PNG —
ESPHome's online_image decoder is unreliable with 1-bit PNGs.
"""
from __future__ import annotations

import io

import qrcode
from PIL import Image, ImageDraw, ImageFont

# Portrait composition size (rotated to the panel at the end).
PW, PH = 480, 800
_MARGIN = 40


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _portrait():
    img = Image.new("L", (PW, PH), color=255)
    return img, ImageDraw.Draw(img)


def _center_text(draw, y, text, size, fill=0):
    f = _font(size)
    w = draw.textlength(text, font=f)
    draw.text(((PW - w) / 2, y), text, font=f, fill=fill)
    return y + size


def _ink_mark(draw, cx, cy):
    """The organic ink blob + dot, centered at (cx, cy)."""
    draw.ellipse((cx - 34, cy - 34, cx + 34, cy + 34), fill=0)
    draw.ellipse((cx + 6, cy + 2, cx + 38, cy + 34), fill=0)
    draw.ellipse((cx + 24, cy - 40, cx + 44, cy - 20), fill=0)


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
    _ink_mark(draw, PW // 2 - 28, 96)
    _center_text(draw, 150, "Ink", 64)
    draw.line((_MARGIN, 236, PW - _MARGIN, 236), fill=0, width=3)


# --------------------------------------------------------------------------- #
def onboarding_splash(app_url: str, ap_name: str) -> bytes:
    """Stage A — no WiFi yet: how to install the app + join the frame's WiFi."""
    img, draw = _portrait()
    _masthead(draw)
    _center_text(draw, 262, "Let's get started", 30)
    qr = _qr(app_url, box=5)
    img.paste(qr, ((PW - qr.width) // 2, 320))
    y = 320 + qr.height + 16
    _center_text(draw, y, "1.  Scan to get the Ink app", 22)
    _center_text(draw, y + 34, f"2.  Join Wi-Fi “{ap_name}”", 22)
    _center_text(draw, y + 68, "3.  Pick your home Wi-Fi", 22)
    return _finish(img)


def pairing_splash(code: str, pair_url: str) -> bytes:
    """Stage B — on WiFi, not paired: pairing code + QR to scan in the app."""
    img, draw = _portrait()
    _masthead(draw)
    _center_text(draw, 262, "Pair your frame", 30)
    qr = _qr(pair_url, box=6)
    img.paste(qr, ((PW - qr.width) // 2, 312))
    y = 312 + qr.height + 18
    _center_text(draw, y, "Scan this with the Ink app", 22)
    _center_text(draw, y + 40, "Pairing code", 22)
    _center_text(draw, y + 70, code, 60)
    return _finish(img)


def connect_splash(ap_name: str) -> bytes:
    """Paired, waiting for the first artwork."""
    img, draw = _portrait()
    _masthead(draw)
    _center_text(draw, 300, "You're paired!", 32)
    _center_text(draw, 360, "Your first work of art", 24)
    _center_text(draw, 392, "is on its way.", 24)
    return _finish(img)
