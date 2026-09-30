"""Playwright isolated browser context factory with security lock auto-injection."""

import logging
from typing import Optional, Tuple
from playwright.sync_api import Browser, BrowserContext, Playwright

from qr_form_agent.browser.locks import ANTI_SUBMIT_INIT_SCRIPT

logger = logging.getLogger(__name__)


def create_isolated_context(
    playwright: Playwright,
    headless: bool = True,
    inject_locks: bool = True,
    browser_instance: Optional[Browser] = None,
) -> Tuple[Browser, BrowserContext]:
    """
    Creates an isolated Browser and BrowserContext.
    Each URL/job operates in complete isolation with no shared storage or cookies.
    Automatically injects anti-submission initialization script into all frames.
    """
    browser = browser_instance or playwright.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        java_script_enabled=True,
        accept_downloads=False,
    )

    if inject_locks:
        context.add_init_script(ANTI_SUBMIT_INIT_SCRIPT)
        logger.debug("Injected anti-submit init script into isolated BrowserContext.")

    return browser, context


class TupleBrowser:
    """Type alias container for (Browser, BrowserContext) tuple."""
    pass
