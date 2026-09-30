"""Live DOM vs. approved snapshot hash verification module."""

import logging
from typing import Any, Dict, Tuple
from playwright.sync_api import Page

from qr_form_agent.fill.snapshot import compute_snapshot_hash, extract_live_form_values

logger = logging.getLogger(__name__)


def verify_dom_matches_approved_snapshot(
    page: Page,
    field_selectors: Dict[str, str],
    approved_snapshot_hash: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Re-checks that current live DOM field values hash-match the approved snapshot.
    Aborts on even a single-character discrepancy.
    Returns: (is_match, current_hash, live_field_values)
    """
    live_values = extract_live_form_values(page, field_selectors)
    current_hash = compute_snapshot_hash(live_values)

    is_match = (current_hash == approved_snapshot_hash)
    if not is_match:
        logger.critical(
            "[SECURITY VIOLATION] Live DOM hash mismatch! Approved: %s, Current Live: %s",
            approved_snapshot_hash,
            current_hash,
        )

    return is_match, current_hash, live_values
