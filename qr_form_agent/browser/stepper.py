"""Multi-step form navigation and headful human takeover handler."""

import logging
from typing import Optional
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

logger = logging.getLogger(__name__)


def detect_multi_step_controls(page: Page) -> Optional[str]:
    """
    Detects if there is a clear, unambiguous 'Next' / 'Continue' button that is NOT a submit button.
    Returns CSS selector if found and safe, else None.
    """
    candidates = [
        'button:has-text("Next")',
        'button:has-text("Continue")',
        'input[type="button"][value="Next"]',
        'a:has-text("Next Step")',
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                btn_type = loc.first.get_attribute("type")
                # Must NOT be a submit button!
                if btn_type != "submit":
                    return sel
        except Exception:
            continue
    return None


def launch_headful_takeover(url: str, prompt_message: str = "Please solve CAPTCHA/Login, then press Enter to resume...") -> None:
    """
    Launches a visible, interactive headful browser window for human takeover
    when an automated task encounters CAPTCHA, Cloudflare challenge, or OTP login.
    """
    print(f"\n[HEADFUL TAKEOVER] Launching interactive browser for: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)
        input(f"\n>>> {prompt_message} (Press Enter when done) <<<")
        browser.close()
    print("[HEADFUL TAKEOVER] Takeover completed. Resuming automated flow.\n")
