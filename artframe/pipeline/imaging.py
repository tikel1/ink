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
            panel = fitted.convert("1").rotate(90, expand=True)  # -> 800x480
        else:
            fitted = _fit(_orient_landscape(rgb), DISPLAY_WIDTH, DISPLAY_HEIGHT)
            panel = fitted.convert("1")  # Pillow default = Floyd-Steinberg
        # Store PNG as 8-bit grayscale (pixels are still pure 0/255 from the
        # dither). ESPHome's online_image decoder is unreliable with 1-bit-depth
        # PNGs; 8-bit decodes cleanly and the dither pattern is preserved.
        out_img = panel.convert("L") if fmt.upper() == "PNG" else panel
        out = io.BytesIO()
        out_img.save(out, format=fmt)
        return out.getvalue()


def to_eink_bmp(source: bytes) -> bytes:
    """Backwards-compatible 1-bit BMP helper (landscape)."""
    return to_eink_image(source, fmt="BMP")


def _orient_landscape(image: Image.Image) -> Image.Image:
    """Rotate portrait sources so the long edge is horizontal."""
    if image.height > image.width:
        return image.rotate(90, expand=True)
    return image


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    """Cover-fit to width x height: scale to fill, center-crop the overflow."""
    target_ratio = width / height
    source_ratio = image.width / image.height
    scale = (height / image.height) if source_ratio > target_ratio else (width / image.width)

    new_size = (round(image.width * scale), round(image.height * scale))
    scaled = image.resize(new_size, Image.LANCZOS)

    left = (scaled.width - width) // 2
    top = (scaled.height - height) // 2
    return scaled.crop((left, top, left + width, top + height))


def save_image(image_bytes: bytes, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return path
