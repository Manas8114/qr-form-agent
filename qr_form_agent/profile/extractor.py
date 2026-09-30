"""PDF text extraction using PyMuPDF with OCR fallback support."""

import io
import logging
from pathlib import Path
from typing import Union
from PIL import Image

try:
    import pymupdf as fitz
except ImportError:
    import fitz

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_input: Union[str, Path, bytes]) -> str:
    """
    Extracts plain text from a PDF document using PyMuPDF.
    If the document contains no extractable text (e.g. image-only scanned PDF),
    it attempts OCR fallback.
    """
    if isinstance(pdf_input, (str, Path)):
        doc = fitz.open(str(pdf_input))
    elif isinstance(pdf_input, bytes):
        doc = fitz.open(stream=pdf_input, filetype="pdf")
    else:
        raise ValueError(f"Unsupported PDF input type: {type(pdf_input)}")

    full_text_parts = []
    try:
        for page_idx, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                full_text_parts.append(text.strip())

        extracted_text = "\n\n".join(full_text_parts).strip()

        # If text is too sparse, attempt OCR fallback
        if len(extracted_text) < 50:
            logger.info("PDF contains insufficient embedded text (< 50 chars). Attempting OCR fallback...")
            ocr_text = _perform_ocr_fallback(doc)
            if ocr_text.strip():
                return ocr_text

        return extracted_text
    finally:
        doc.close()


def _perform_ocr_fallback(doc: fitz.Document) -> str:
    """Fallback OCR on rendered page images."""
    try:
        import pytesseract  # type: ignore
    except ImportError:
        logger.warning("pytesseract is not installed; OCR fallback unavailable.")
        return ""

    ocr_pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        try:
            text = pytesseract.image_to_string(img)
            if text.strip():
                ocr_pages.append(text.strip())
        except Exception as e:
            logger.warning("OCR failed on page: %s", e)

    return "\n\n".join(ocr_pages).strip()
