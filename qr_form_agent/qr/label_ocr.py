"""Spatial label OCR for QR codes on printed job fair boards and flyers.

Enforces Requirement 3:
Reads printed labels near each QR code to associate company, role, deadline,
and opening/closing notices with the decoded URL.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:
    import pytesseract
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False


class QRLabelMetadata(BaseModel):
    url: str
    company: Optional[str] = None
    role: Optional[str] = None
    deadline: Optional[str] = None
    opening_date: Optional[str] = None
    notes: Optional[str] = None
    raw_ocr_text: Optional[str] = None
    bounding_box: Optional[Tuple[int, int, int, int]] = None  # (min_x, min_y, max_x, max_y)


# Common role keywords for heuristic extraction
COMMON_ROLE_PATTERNS = [
    r"(software\s+engineer(?:\s+intern|\s+graduate)?|\w+\s+developer|data\s+scientist|analyst|product\s+manager|quant(?:itative)?\s+(?:trader|researcher|developer)|systems\s+engineer|frontend\s+engineer|backend\s+engineer|full\s*stack\s+engineer|devops\s+engineer|cloud\s+engineer|security\s+engineer)",
]

# Patterns for deadlines & notices
DEADLINE_PATTERNS = [
    r"(?:deadline|closes|due|apply\s+by)[:\s]+([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+(?:\s+[0-9]{4})?|[A-Za-z]+\s+[0-9]{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*[0-9]{4})?|[0-9]{4}-[0-9]{2}-[0-9]{2})",
]

OPENING_PATTERNS = [
    r"(?:opens\s+in|starts\s+in|available\s+in|opening\s+in)[:\s]+([A-Za-z]+(?:\s+[0-9]{4})?)",
]

NOTICE_PATTERNS = [
    r"(applications?\s+(?:are\s+)?closed|position\s+filled|closed|no\s+longer\s+accepting)",
    r"(uk\s+citizens?\s+only|us\s+citizens?\s+only|visa\s+sponsorship\s+not\s+available|sponsorship\s+available)",
]


def extract_text_from_image_region(image: Image.Image, box: Tuple[int, int, int, int]) -> str:
    """Crops the specified region from image and runs OCR."""
    min_x, min_y, max_x, max_y = box
    width, height = image.size

    # Clamp coordinates
    min_x = max(0, min(min_x, width - 1))
    min_y = max(0, min(min_y, height - 1))
    max_x = max(min_x + 1, min(max_x, width))
    max_y = max(min_y + 1, min(max_y, height))

    cropped = image.crop((min_x, min_y, max_x, max_y))

    if not HAS_PYTESSERACT:
        return ""

    try:
        text = pytesseract.image_to_string(cropped)
        return text.strip()
    except Exception as e:
        logger.debug("Tesseract OCR error on cropped region: %s", e)
        return ""


def parse_metadata_from_text(raw_text: str) -> Dict[str, Optional[str]]:
    """Extracts structured company, role, deadline, and notes from raw OCR text."""
    if not raw_text:
        return {"company": None, "role": None, "deadline": None, "opening_date": None, "notes": None}

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    company: Optional[str] = None
    role: Optional[str] = None
    deadline: Optional[str] = None
    opening_date: Optional[str] = None
    notes_list: List[str] = []

    # 1. Search for deadline
    for pat in DEADLINE_PATTERNS:
        match = re.search(pat, raw_text, re.IGNORECASE)
        if match:
            deadline = match.group(1).strip()
            break

    # 2. Search for opening dates (e.g. "opens in December")
    for pat in OPENING_PATTERNS:
        match = re.search(pat, raw_text, re.IGNORECASE)
        if match:
            opening_date = match.group(1).strip()
            notes_list.append(f"Opens in {opening_date}")
            break

    # 3. Search for notices (closed, sponsorship, etc.)
    for pat in NOTICE_PATTERNS:
        match = re.search(pat, raw_text, re.IGNORECASE)
        if match:
            notes_list.append(match.group(1).strip().capitalize())

    # 4. Search for role patterns
    for pat in COMMON_ROLE_PATTERNS:
        match = re.search(pat, raw_text, re.IGNORECASE)
        if match:
            role = match.group(1).strip().title()
            break

    # 5. Extract company name: usually first clean line that isn't a role or date
    for line in lines:
        cleaned = re.sub(r"[^\w\s&.-]", "", line).strip()
        if not cleaned or len(cleaned) < 2:
            continue
        if role and cleaned.lower() == role.lower():
            continue
        if any(w in cleaned.lower() for w in ("deadline", "closes", "opens", "scan", "qr", "apply", "http")):
            continue
        # High likelihood of company name
        company = cleaned
        break

    return {
        "company": company,
        "role": role,
        "deadline": deadline,
        "opening_date": opening_date,
        "notes": "; ".join(notes_list) if notes_list else None,
    }


def extract_qr_labels(image: Image.Image, barcodes: List[Any]) -> List[QRLabelMetadata]:
    """
    Given a PIL Image and a list of detected zxing-cpp Barcode objects,
    extracts spatial OCR regions surrounding each QR code and extracts label metadata.
    """
    results: List[QRLabelMetadata] = []
    width, height = image.size

    for barcode in barcodes:
        url = barcode.text
        if not url:
            continue

        # Compute bounding box of QR code
        points = barcode.position
        min_x = min(p.x for p in (points.top_left, points.top_right, points.bottom_right, points.bottom_left))
        max_x = max(p.x for p in (points.top_left, points.top_right, points.bottom_right, points.bottom_left))
        min_y = min(p.y for p in (points.top_left, points.top_right, points.bottom_right, points.bottom_left))
        max_y = max(p.y for p in (points.top_left, points.top_right, points.bottom_right, points.bottom_left))

        qr_w = max_x - min_x
        qr_h = max_y - min_y

        # Region above QR code (header label: Company, Role)
        top_box = (
            int(max(0, min_x - qr_w * 0.4)),
            int(max(0, min_y - qr_h * 1.5)),
            int(min(width, max_x + qr_w * 0.4)),
            int(min_y),
        )

        # Region below QR code (footer label: Deadline, Notices)
        bottom_box = (
            int(max(0, min_x - qr_w * 0.4)),
            int(max_y),
            int(min(width, max_x + qr_w * 0.4)),
            int(min(height, max_y + qr_h * 1.2)),
        )

        text_top = extract_text_from_image_region(image, top_box)
        text_bottom = extract_text_from_image_region(image, bottom_box)
        combined_text = f"{text_top}\n{text_bottom}".strip()

        parsed = parse_metadata_from_text(combined_text)

        results.append(
            QRLabelMetadata(
                url=url,
                company=parsed["company"],
                role=parsed["role"],
                deadline=parsed["deadline"],
                opening_date=parsed["opening_date"],
                notes=parsed["notes"],
                raw_ocr_text=combined_text or None,
                bounding_box=(int(min_x), int(min_y), int(max_x), int(max_y)),
            )
        )

    return results
