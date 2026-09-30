"""Post-submit confirmation receipt and screenshot capture."""

import logging
from pathlib import Path
from typing import Optional, Tuple
from playwright.sync_api import Page
from qr_form_agent.config import settings

logger = logging.getLogger(__name__)


def capture_submission_confirmation(
    page: Page,
    job_id: str,
    custom_screenshot_dir: Optional[Path] = None,
) -> Tuple[str, str]:
    """
    Captures post-submit confirmation screenshot and extracts receipt text.
    Returns: (receipt_summary, confirmation_screenshot_path)
    """
    target_dir = custom_screenshot_dir or (settings.data_dir / "screenshots")
    target_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = target_dir / f"{job_id}_confirmation.png"

    # Capture screenshot
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        page.screenshot(path=str(screenshot_path), full_page=False)

    # Extract confirmation text snippets from DOM
    receipt_text = page.evaluate("""
        (() => {
            const candidates = document.querySelectorAll('h1, h2, h3, .alert, .success, .confirmation, [role="alert"]');
            const texts = [];
            candidates.forEach(el => {
                const t = el.innerText.trim();
                if (t && t.length < 300) texts.push(t);
            });
            return texts.join(' | ') || document.body.innerText.slice(0, 400).trim();
        })()
    """)

    logger.info("Captured submission confirmation for job %s: %s", job_id, receipt_text)
    return receipt_text, str(screenshot_path)
