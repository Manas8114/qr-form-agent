"""Single-hop landing page navigation through SSRF safety gate.

Enforces Requirement 2:
Follows the 'Apply' button from a landing page to the true application form,
strictly routing the target URL through the same SSRF and HTTPS safety gate.
"""

import logging
from typing import Optional, Tuple
from urllib.parse import urljoin
from playwright.sync_api import Page

from qr_form_agent.safety.url_gate import validate_url
from qr_form_agent.triage.classifier import APPLY_BUTTON_SELECTORS, classify_page
from qr_form_agent.triage.models import TriageResult, TriageStatus

logger = logging.getLogger(__name__)


def follow_apply_button(
    page: Page,
    landing_result: TriageResult,
    base_url: str,
) -> Tuple[bool, Optional[str], Optional[TriageResult], str]:
    """
    Executes a single hop from a landing page to the destination application form.
    Validates destination URL through SSRF gate before allowing navigation.
    Returns: (success, destination_url, new_triage_result, message)
    """
    if landing_result.status != TriageStatus.LANDING_PAGE:
        return False, None, None, f"Page is not a landing page (status: {landing_result.status})"

    destination_url: Optional[str] = None
    selector = landing_result.apply_button_selector

    # 1. Use pre-extracted apply destination URL if available
    if landing_result.apply_destination_url and not landing_result.apply_destination_url.startswith("#"):
        destination_url = urljoin(base_url, landing_result.apply_destination_url)

    # Otherwise, try to find link href directly from selector
    if not destination_url and selector:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                raw_href = loc.get_attribute("href")
                if raw_href and not raw_href.startswith("#") and not raw_href.startswith("javascript:"):
                    destination_url = urljoin(base_url, raw_href)
        except Exception as e:
            logger.debug("Failed getting href from selector %s: %s", selector, e)

    # Fallback to scanning standard apply selectors
    if not destination_url:
        for sel in APPLY_BUTTON_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    raw_href = loc.get_attribute("href")
                    if raw_href and not raw_href.startswith("#") and not raw_href.startswith("javascript:"):
                        destination_url = urljoin(base_url, raw_href)
                        selector = sel
                        break
            except Exception:
                continue

    # 2. If destination URL is resolved, validate with SSRF gate and navigate
    if destination_url:
        # Strict SSRF and HTTPS validation on destination hop
        gate_res = validate_url(destination_url, resolve_redirects=True)
        if not gate_res.is_safe:
            msg = f"Apply hop rejected by SSRF/Safety gate: {gate_res.error_reason}"
            logger.warning("[LANDING_HOPPER_BLOCKED] %s", msg)
            return False, destination_url, None, msg

        final_dest = gate_res.final_url or destination_url
        logger.info("[LANDING_HOPPER] Navigating 1-hop from %s to %s", base_url, final_dest)
        try:
            page.goto(final_dest, wait_until="domcontentloaded", timeout=15000)
            new_triage = classify_page(page, final_dest)
            return True, final_dest, new_triage, f"Successfully followed Apply link to {final_dest}"
        except Exception as e:
            return False, final_dest, None, f"Navigation to destination URL failed: {e}"

    # 3. If no direct href, attempt click-based navigation with route protection
    if selector:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible():
                logger.info("[LANDING_HOPPER] Clicking apply button '%s'", selector)
                with page.expect_navigation(timeout=10000):
                    loc.click()

                new_url = page.url
                # Validate new URL after click
                gate_res = validate_url(new_url, resolve_redirects=False)
                if not gate_res.is_safe:
                    return False, new_url, None, f"Post-click destination URL unsafe: {gate_res.error_reason}"

                new_triage = classify_page(page, new_url)
                return True, new_url, new_triage, f"Followed apply button click to {new_url}"
        except Exception as e:
            logger.debug("Click navigation failed: %s", e)

    return False, None, None, "Could not find valid Apply button or destination link"
