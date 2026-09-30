"""Safe form population module.

Enforces Hard Requirement 1:
- The fill module must not expose any click on submit-type elements.
- Submissions are physically blocked by route guards and anti-submit event capture.
- Only populates field values (input, select, textarea, checkbox, radio).
"""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from playwright.sync_api import Locator, Page

from qr_form_agent.browser.dom_extractor import FormFieldDescriptor
from qr_form_agent.fill.uploader import upload_resume_if_requested

logger = logging.getLogger(__name__)


class FillItem(BaseModel):
    field_id: str
    selector: str
    value: Any
    field_type: str = "text"
    is_resume_upload: bool = False
    flagged_for_review: bool = False


class FillSummary(BaseModel):
    filled_fields: List[str] = Field(default_factory=list)
    skipped_fields: List[str] = Field(default_factory=list)
    failed_fields: List[str] = Field(default_factory=list)


def is_forbidden_submit_element(locator: Locator) -> bool:
    """Verifies that an element is not a button or submit element."""
    try:
        tag = locator.evaluate("el => el.tagName.toLowerCase()")
        el_type = locator.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
        if tag == "button" or el_type in ("submit", "image"):
            return True
    except Exception:
        pass
    return False


def populate_single_field(page: Page, item: FillItem, resume_path: Optional[str] = None) -> bool:
    """
    Safely populates a single form field without triggering any form submissions.
    """
    if item.value is None and not item.is_resume_upload:
        logger.debug("Skipping field %s: value is null", item.field_id)
        return False

    loc = page.locator(item.selector).first
    if loc.count() == 0:
        logger.warning("Locator not found for field %s (%s)", item.field_id, item.selector)
        return False

    # Guard: Never interact with submit elements - fail immediately!
    if is_forbidden_submit_element(loc):
        raise PermissionError(f"Security invariant violated: attempted to interact with submit element {item.selector}")

    try:
        tag = loc.evaluate("el => el.tagName.toLowerCase()")
        el_type = loc.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")

        # 1. File Upload
        if el_type == "file":
            if item.is_resume_upload:
                return upload_resume_if_requested(
                    page, item.selector, resume_path, flagged_for_review=item.flagged_for_review
                )
            return False

        # 2. Select Dropdown
        if tag == "select":
            str_val = str(item.value)
            loc.select_option(value=str_val)
            loc.dispatch_event("change")
            return True

        # 3. Checkbox
        if el_type == "checkbox":
            desired_state = bool(item.value)
            loc.set_checked(desired_state)
            loc.dispatch_event("change")
            return True

        # 4. Radio Button
        if el_type == "radio":
            loc.check()
            loc.dispatch_event("change")
            return True

        # 5. Standard Text / Textarea / Email / Tel
        str_val = str(item.value)
        loc.fill(str_val)
        loc.dispatch_event("input")
        loc.dispatch_event("change")
        return True

    except Exception as e:
        logger.warning("Failed to populate field %s (%s): %s", item.field_id, item.selector, e)
        return False


def fill_form_fields(
    page: Page,
    items: List[FillItem],
    resume_path: Optional[str] = None,
) -> FillSummary:
    """
    Populates an entire list of form fields in the page safely.
    Exposes no submission logic.
    """
    summary = FillSummary()

    for item in items:
        if item.value is None and not item.is_resume_upload:
            summary.skipped_fields.append(item.field_id)
            continue

        success = populate_single_field(page, item, resume_path=resume_path)
        if success:
            summary.filled_fields.append(item.field_id)
        else:
            summary.failed_fields.append(item.field_id)

    return summary
