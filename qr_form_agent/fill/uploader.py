"""Safe resume file upload handler with review flag enforcement."""

import logging
from pathlib import Path
from typing import Optional
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def upload_resume_if_requested(
    page: Page,
    selector: str,
    resume_path: Optional[str],
    flagged_for_review: bool,
) -> bool:
    """
    Safely uploads a resume file ONLY if:
      1. The field is an input of type 'file'
      2. It has been explicitly flagged for human review
      3. The resume file path exists on disk
    """
    if not flagged_for_review:
        logger.info("Resume upload skipped: field not flagged for review.")
        return False

    if not resume_path or not Path(resume_path).exists():
        logger.warning("Resume upload skipped: file path %s does not exist.", resume_path)
        return False

    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            logger.warning("File input selector %s not found.", selector)
            return False

        input_type = loc.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
        if input_type != "file":
            logger.error("Security violation: Attempted to upload file to non-file element (%s).", input_type)
            return False

        loc.set_input_files(resume_path)
        logger.info("Successfully attached resume %s to %s", resume_path, selector)
        return True
    except Exception as e:
        logger.error("Failed to upload resume file to %s: %s", selector, e)
        return False
