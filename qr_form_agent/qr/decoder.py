"""QR code decoder using zxing-cpp with multi-stage fallback preprocessors."""

import io
import logging
from pathlib import Path
from typing import List, Set, Union
from PIL import Image
from pydantic import BaseModel, Field
import zxingcpp

from qr_form_agent.qr.preprocessors import (
    apply_contrast_and_threshold,
    generate_overlapping_crops,
    to_grayscale,
    upscale_image,
)

logger = logging.getLogger(__name__)


class QRItem(BaseModel):
    text: str = Field(description="Decoded QR payload text/URL")
    format: str = Field(default="QRCode", description="Barcode format name")
    detection_method: str = Field(description="Pipeline stage that successfully decoded the QR code")


class QRScanResult(BaseModel):
    items: List[QRItem] = Field(default_factory=list, description="All detected QR code items")
    urls: List[str] = Field(default_factory=list, description="Deduplicated decoded URLs/payloads")
    total_found: int = Field(default=0, description="Total QR codes decoded before deduplication")
    unique_count: int = Field(default=0, description="Count of unique QR payloads detected")


def _read_image(image_input: Union[str, Path, bytes, Image.Image]) -> Image.Image:
    """Normalize input into an RGB PIL Image."""
    if isinstance(image_input, Image.Image):
        img = image_input
    elif isinstance(image_input, bytes):
        img = Image.open(io.BytesIO(image_input))
    elif isinstance(image_input, (str, Path)):
        img = Image.open(Path(image_input))
    else:
        raise ValueError(f"Unsupported image input type: {type(image_input)}")

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def decode_qr_codes(
    image_input: Union[str, Path, bytes, Image.Image],
    enable_fallbacks: bool = True,
) -> QRScanResult:
    """
    Decodes all QR codes from an image using zxing-cpp.
    Applies multi-stage fallback preprocessing:
      1. Direct detection
      2. Upscaling (2x)
      3. Contrast & adaptive thresholding
      4. Overlapping windowed tiling (for high-resolution dense sheets)
    Deduplicates results and returns a comprehensive QRScanResult.
    """
    base_image = _read_image(image_input)
    found_items: List[QRItem] = []
    seen_texts: Set[str] = set()

    def _scan(img: Image.Image, method_name: str) -> None:
        try:
            # We explicitly scan for QRCode format with rotation enabled
            results = zxingcpp.read_barcodes(
                img,
                formats=zxingcpp.BarcodeFormat.QRCode,
                try_rotate=True,
                try_downscale=True,
            )
            for res in results:
                raw_text = res.text.strip()
                if raw_text:
                    found_items.append(
                        QRItem(
                            text=raw_text,
                            format=res.format.name,
                            detection_method=method_name,
                        )
                    )
                    seen_texts.add(raw_text)
        except Exception as e:
            logger.debug("Scan failed under method %s: %s", method_name, e)

    # Stage 1: Direct scan
    _scan(base_image, "direct")

    # If fallbacks disabled, return immediate findings
    if not enable_fallbacks:
        unique_urls = list(dict.fromkeys([item.text for item in found_items]))
        return QRScanResult(
            items=found_items,
            urls=unique_urls,
            total_found=len(found_items),
            unique_count=len(unique_urls),
        )

    # Stage 2: Grayscale + Upscale (resolves small/low-res QR codes)
    gray = to_grayscale(base_image)
    upscaled = upscale_image(gray, factor=2.0)
    _scan(upscaled, "upscale_2x")

    # Stage 3: Contrast and binary thresholding (resolves washed-out / noisy codes)
    thresh = apply_contrast_and_threshold(base_image, threshold=130)
    _scan(thresh, "thresholding")

    # Stage 4: Overlapping tiled crops (resolves dense multi-QR layouts or high-res images)
    tiles = generate_overlapping_crops(base_image, tile_size=(600, 600), overlap_ratio=0.3)
    if len(tiles) > 1:
        for idx, tile in enumerate(tiles):
            _scan(tile, f"tiled_crop_{idx}")

    # Deduplicate preserving order
    deduped_urls: List[str] = []
    for item in found_items:
        if item.text not in deduped_urls:
            deduped_urls.append(item.text)

    return QRScanResult(
        items=found_items,
        urls=deduped_urls,
        total_found=len(found_items),
        unique_count=len(deduped_urls),
    )
