"""Tests for QR code detection, fallbacks, deduplication, and counting."""

import io
import pytest
from PIL import Image, ImageDraw, ImageEnhance
import qrcode

from qr_form_agent.qr.decoder import decode_qr_codes
from qr_form_agent.qr.preprocessors import (
    apply_contrast_and_threshold,
    generate_overlapping_crops,
    upscale_image,
)


def _generate_qr_image(url: str, size: int = 250) -> Image.Image:
    """Helper to generate a clean QR code PIL Image."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    if hasattr(img, "get_image"):
        img = img.get_image()
    return img.convert("RGB").resize((size, size))


def test_single_qr_detection():
    url = "https://apply.example.com/job/101"
    img = _generate_qr_image(url)
    result = decode_qr_codes(img)

    assert result.total_found >= 1
    assert result.unique_count == 1
    assert url in result.urls


def test_multiple_qr_detection_in_single_canvas():
    urls = [
        "https://careers.corp.com/apply/frontend",
        "https://careers.corp.com/apply/backend",
        "https://careers.corp.com/apply/devops",
    ]

    # Create a 900x400 canvas and paste 3 QR codes side-by-side
    canvas = Image.new("RGB", (900, 300), color="white")
    for idx, u in enumerate(urls):
        qr_img = _generate_qr_image(u, size=220)
        canvas.paste(qr_img, (idx * 300 + 40, 40))

    result = decode_qr_codes(canvas)

    assert result.unique_count == 3
    for u in urls:
        assert u in result.urls


def test_qr_deduplication():
    # If the same URL appears twice on a page, dedupe must report 1 unique URL
    url = "https://careers.example.com/apply"
    canvas = Image.new("RGB", (600, 300), color="white")
    qr1 = _generate_qr_image(url, size=200)
    qr2 = _generate_qr_image(url, size=200)
    canvas.paste(qr1, (20, 50))
    canvas.paste(qr2, (320, 50))

    result = decode_qr_codes(canvas)
    assert result.unique_count == 1
    assert result.urls == [url]


def test_small_qr_upscaling_fallback():
    url = "https://tiny.example.com/small-code"
    # Make a tiny 60x60 QR code where upscaling helps detection
    tiny_qr = _generate_qr_image(url, size=70)

    # Test direct preprocessor
    upscaled = upscale_image(tiny_qr, factor=3.0)
    assert upscaled.size == (210, 210)

    result = decode_qr_codes(tiny_qr, enable_fallbacks=True)
    assert url in result.urls


def test_low_contrast_threshold_fallback():
    url = "https://washed.example.com/low-contrast"
    qr_img = _generate_qr_image(url, size=250)

    # Degrade contrast significantly
    enhancer = ImageEnhance.Contrast(qr_img)
    degraded = enhancer.enhance(0.2)  # Low contrast grayish

    # Ensure preprocessor runs without errors
    thresh = apply_contrast_and_threshold(degraded, threshold=128)
    assert thresh.mode == "1"

    result = decode_qr_codes(degraded, enable_fallbacks=True)
    assert url in result.urls


def test_tiled_crops_fallback_on_large_canvas():
    # Create a 1400x1400 canvas with QR codes in distant corners
    large_canvas = Image.new("RGB", (1400, 1400), color="white")
    u1 = "https://corner1.example.com/pos"
    u2 = "https://corner2.example.com/pos"

    large_canvas.paste(_generate_qr_image(u1, size=250), (50, 50))
    large_canvas.paste(_generate_qr_image(u2, size=250), (1050, 1050))

    crops = generate_overlapping_crops(large_canvas, tile_size=(600, 600), overlap_ratio=0.25)
    assert len(crops) > 1

    result = decode_qr_codes(large_canvas, enable_fallbacks=True)
    assert u1 in result.urls
    assert u2 in result.urls
    assert result.unique_count == 2
