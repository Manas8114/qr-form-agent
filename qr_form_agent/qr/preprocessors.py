"""Image preprocessing fallbacks for robust QR code detection."""

from typing import List, Tuple
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def to_grayscale(image: Image.Image) -> Image.Image:
    """Convert an image to 8-bit grayscale."""
    if image.mode != "L":
        return image.convert("L")
    return image


def upscale_image(image: Image.Image, factor: float = 2.0) -> Image.Image:
    """Upscale image using bicubic interpolation to make small or low-res QR codes detectable."""
    new_width = int(image.width * factor)
    new_height = int(image.height * factor)
    return image.resize((new_width, new_height), Image.Resampling.BICUBIC)


def apply_contrast_and_threshold(image: Image.Image, threshold: int = 128) -> Image.Image:
    """Enhance contrast and apply point thresholding."""
    gray = to_grayscale(image)
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(2.0)
    # Thresholding: pixels >= threshold become 255, else 0
    return enhanced.point(lambda p: 255 if p >= threshold else 0, mode="1")


def generate_overlapping_crops(
    image: Image.Image,
    tile_size: Tuple[int, int] = (600, 600),
    overlap_ratio: float = 0.25,
) -> List[Image.Image]:
    """
    Generate overlapping tiled crops for high-resolution images containing multiple QR codes.
    If the image is smaller than tile_size, returns [image].
    """
    width, height = image.size
    tile_w, tile_h = tile_size

    if width <= tile_w and height <= tile_h:
        return [image]

    step_x = max(int(tile_w * (1.0 - overlap_ratio)), 50)
    step_y = max(int(tile_h * (1.0 - overlap_ratio)), 50)

    tiles: List[Image.Image] = []

    for y in range(0, height, step_y):
        box_y2 = min(y + tile_h, height)
        box_y1 = max(0, box_y2 - tile_h)
        for x in range(0, width, step_x):
            box_x2 = min(x + tile_w, width)
            box_x1 = max(0, box_x2 - tile_w)
            tile = image.crop((box_x1, box_y1, box_x2, box_y2))
            tiles.append(tile)

    return tiles
