"""Onboarding splash screens as 1-bit PNGs for unpaired devices."""
from __future__ import annotations

import io

import qrcode
from PIL import Image, ImageDraw, ImageFont

from artframe.constants import DISPLAY_HEIGHT, DISPLAY_WIDTH

_MARGIN = 48
_QR_BOX = 6


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _canvas():
    img = Image.new("1", (DISPLAY_WIDTH, DISPLAY_HEIGHT), color=1)
    return img, ImageDraw.Draw(img)


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("1").save(out, format="PNG")
    return out.getvalue()


def connect_splash(ap_name: str) -> bytes:
    img, draw = _canvas()
    lines = [
        ("Ink", 72),
        ("Let's get connected", 32),
        ("", 16),
        ("1. Hold the button 5 seconds", 26),
        (f"2. Join WiFi: {ap_name}", 26),
        ("3. Enter your home WiFi", 26),
    ]
    total = sum(sz + 12 for _, sz in lines)
    y = (DISPLAY_HEIGHT - total) // 2
    for text, sz in lines:
        f = _font(sz)
        w = draw.textlength(text, font=f)
        draw.text(((DISPLAY_WIDTH - w) // 2, y), text, font=f, fill=0)
        y += sz + 12
    return _png(img)


def pairing_splash(code: str, pair_url: str) -> bytes:
    img, draw = _canvas()
    draw.text((_MARGIN, _MARGIN), "Not paired", font=_font(40), fill=0)
    draw.text((_MARGIN, 110), "No app is connected to", font=_font(22), fill=0)
    draw.text((_MARGIN, 138), "this frame yet.", font=_font(22), fill=0)
    draw.text((_MARGIN, 196), "Pairing code", font=_font(24), fill=0)
    draw.text((_MARGIN, 230), code, font=_font(76), fill=0)
    draw.text((_MARGIN, 330), "Scan the QR, or enter", font=_font(24), fill=0)
    draw.text((_MARGIN, 360), "this code in the Ink app.", font=_font(24), fill=0)

    qr = qrcode.QRCode(box_size=_QR_BOX, border=2)
    qr.add_data(pair_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("1")
    img.paste(qr_img, (DISPLAY_WIDTH - qr_img.width - _MARGIN, 140))
    return _png(img)
