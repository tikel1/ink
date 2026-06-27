"""Tests for the e-ink imaging pipeline."""
import io

from PIL import Image

from artframe.constants import DISPLAY_HEIGHT, DISPLAY_WIDTH
from artframe.pipeline.imaging import to_eink_image


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


def test_png_output_is_1bit_at_panel_size():
    out = to_eink_image(_png(1536, 1024), fmt="PNG")
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "PNG"
        assert img.mode == "1"
        assert img.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)


def test_portrait_source_is_rotated_to_landscape():
    out = to_eink_image(_png(480, 800), fmt="PNG")
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)


def test_bmp_format_still_supported():
    out = to_eink_image(_png(1024, 1024), fmt="BMP")
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "BMP"
        assert img.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
