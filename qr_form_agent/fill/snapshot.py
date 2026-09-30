"""Cryptographic form snapshot generator and screenshot capture."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from playwright.sync_api import Page

from qr_form_agent.config import settings

logger = logging.getLogger(__name__)


def compute_snapshot_hash(field_values: Dict[str, Any]) -> str:
    """
    Computes a deterministic SHA-256 hash of the field mapping dictionary.
    Keys are sorted alphabetically and canonical JSON formatting is enforced.
    """
    # Normalize values: None -> null, strip strings
    normalized: Dict[str, Any] = {}
    for k in sorted(field_values.keys()):
        val = field_values[k]
        if isinstance(val, str):
            normalized[k] = val.strip()
        else:
            normalized[k] = val

    canonical_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def extract_live_form_values(page: Page, field_selectors: Dict[str, str]) -> Dict[str, Any]:
    """
    Reads the current live values of specified fields directly from the browser DOM.
    field_selectors maps field_id -> CSS selector.
    """
    live_values: Dict[str, Any] = {}

    for field_id, selector in field_selectors.items():
        try:
            loc = page.locator(selector).first
            if loc.count() == 0:
                live_values[field_id] = None
                continue

            tag_name = loc.evaluate("el => el.tagName.toLowerCase()")
            input_type = loc.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")

            if input_type in ("checkbox", "radio"):
                live_values[field_id] = loc.is_checked()
            elif tag_name == "select":
                live_values[field_id] = loc.input_value()
            else:
                live_values[field_id] = loc.input_value()
        except Exception as e:
            logger.debug("Failed to read live value for field %s (%s): %s", field_id, selector, e)
            live_values[field_id] = None

    return live_values


def capture_form_snapshot(
    page: Page,
    job_id: str,
    field_selectors: Dict[str, str],
    custom_screenshot_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], str, str]:
    """
    Reads live field values, generates SHA-256 snapshot hash, and captures a full-page screenshot.
    Returns: (live_values, snapshot_hash, screenshot_file_path)
    """
    live_values = extract_live_form_values(page, field_selectors)
    snapshot_hash = compute_snapshot_hash(live_values)

    target_dir = custom_screenshot_dir or (settings.data_dir / "screenshots")
    target_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = target_dir / f"{job_id}_snapshot.png"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        logger.info("Captured form snapshot screenshot: %s", screenshot_path)
    except Exception as e:
        logger.warning("Full-page screenshot failed, trying viewport: %s", e)
        page.screenshot(path=str(screenshot_path), full_page=False)

    return live_values, snapshot_hash, str(screenshot_path)
