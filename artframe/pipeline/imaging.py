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


def to_eink_image(source: bytes, fmt: str = "PNG") -> bytes:
    """Return 1-bit image bytes sized exactly DISPLAY_WIDTH x DISPLAY_HEIGHT.

    `fmt` is "PNG" (served to the ESPHome frame) or "BMP". Floyd-Steinberg
    dithering to pure black & white gives a crisp panel render.
    """
    with Image.open(io.BytesIO(source)) as raw:
        landscape = _orient_landscape(raw.convert("RGB"))
        fitted = _fit_to_panel(landscape)
        dithered = fitted.convert("1")  # Pillow default = Floyd-Steinberg
        out = io.BytesIO()
        dithered.save(out, format=fmt)
        return out.getvalue()


def to_eink_bmp(source: bytes) -> bytes:
    """Backwards-compatible 1-bit BMP helper."""
    return to_eink_image(source, fmt="BMP")


def _orient_landscape(image: Image.Image) -> Image.Image:
    """Rotate portrait sources so the long edge is horizontal."""
    if image.height > image.width:
        return image.rotate(90, expand=True)
    return image


def _fit_to_panel(image: Image.Image) -> Image.Image:
    """Cover-fit to the panel: scale to fill, center-crop the overflow."""
    target_ratio = DISPLAY_WIDTH / DISPLAY_HEIGHT
    source_ratio = image.width / image.height

    if source_ratio > target_ratio:
        scale = DISPLAY_HEIGHT / image.height
    else:
        scale = DISPLAY_WIDTH / image.width

    new_size = (round(image.width * scale), round(image.height * scale))
    scaled = image.resize(new_size, Image.LANCZOS)

    left = (scaled.width - DISPLAY_WIDTH) // 2
    top = (scaled.height - DISPLAY_HEIGHT) // 2
    return scaled.crop((left, top, left + DISPLAY_WIDTH, top + DISPLAY_HEIGHT))


def save_image(image_bytes: bytes, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return path
