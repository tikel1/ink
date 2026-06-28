"""Convert a generated image into a 1-bit 800x480 image for the e-ink panel.

Replaces the HA `shell_command.prepare_rotated_artwork` step. All resizing and
Floyd-Steinberg dithering happen here, so the device renders the pre-dithered
image directly with no on-device scaling.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from ..constants import DISPLAY_HEIGHT, DISPLAY_WIDTH


def to_eink_image(source: bytes, fmt: str = "PNG", orientation: str = "landscape") -> bytes:
    """Return 1-bit bytes sized exactly DISPLAY_WIDTH x DISPLAY_HEIGHT (the panel).

    The panel is physically 800x480. For a portrait-mounted frame we compose the
    art at 480x800, dither, then rotate 90° into the 800x480 buffer so it reads
    upright when the frame hangs vertically. `fmt` is "PNG" (frame) or "BMP".
    """
    with Image.open(io.BytesIO(source)) as raw:
        rgb = raw.convert("RGB")
        if orientation == "portrait":
            fitted = _fit(rgb, DISPLAY_HEIGHT, DISPLAY_WIDTH)  # 480x800
            panel = _binarize(fitted).rotate(90, expand=True)  # -> 800x480
        else:
            fitted = _fit(_orient_landscape(rgb), DISPLAY_WIDTH, DISPLAY_HEIGHT)
            panel = _binarize(fitted)
        # `panel` is 8-bit grayscale with pure 0/255 pixels. ESPHome's
        # online_image decoder is unreliable with 1-bit-depth PNGs, so keep PNG
        # 8-bit; BMP stays 1-bit for size.
        out_img = panel if fmt.upper() == "PNG" else panel.convert("1")
        out = io.BytesIO()
        out_img.save(out, format=fmt)
        return out.getvalue()


def to_eink_bmp(source: bytes) -> bytes:
    """Backwards-compatible 1-bit BMP helper (landscape)."""
    return to_eink_image(source, fmt="BMP")


# Pixels at/above this 0-255 luminance become white, below become black. A hard
# threshold keeps flat paper-cut art crisp and the background pure white — unlike
# Floyd-Steinberg dithering, which speckles every off-white pixel into noise.
_BW_THRESHOLD = 128


def _binarize(image: Image.Image) -> Image.Image:
    """Threshold to pure black/white (mode 'L', values 0 or 255 only)."""
    return image.convert("L").point(lambda p: 255 if p >= _BW_THRESHOLD else 0)


def _orient_landscape(image: Image.Image) -> Image.Image:
    """Rotate portrait sources so the long edge is horizontal."""
    if image.height > image.width:
        return image.rotate(90, expand=True)
    return image


# White margin on each side of the panel, as a fraction of width/height. Keeps
# the whole artwork (incl. the signature) visible — no edge cropping — and gives
# a clean matted border. Applied here in post-processing, never in the prompt.
_MARGIN = 0.05


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    """Contain-fit the whole image inside a `width`x`height` white canvas, leaving
    a `_MARGIN` border on every side. Nothing is cropped (letterboxed instead)."""
    inner_w = max(1, round(width * (1 - 2 * _MARGIN)))
    inner_h = max(1, round(height * (1 - 2 * _MARGIN)))
    scale = min(inner_w / image.width, inner_h / image.height)

    new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    scaled = image.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    canvas.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2))
    return canvas


def save_image(image_bytes: bytes, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return path
