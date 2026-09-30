"""Page classifier for triaging career pages before filling.

Enforces Requirement 1:
Inspects pages to determine if they are FORM, LANDING_PAGE, LOGIN_WALL, CLOSED, or DEAD.
"""

import logging
import re
from typing import Optional, Tuple
from playwright.sync_api import Page
from qr_form_agent.triage.models import TriageResult, TriageStatus

logger = logging.getLogger(__name__)

# Keywords indicating that an application is closed or expired
CLOSED_PATTERNS = [
    r"no\s+longer\s+accepting\s+applications",
    r"applications?\s+(?:are\s+)?closed",
    r"this\s+(?:job|position|role|posting)\s+is\s+closed",
    r"this\s+(?:job|position|role)\s+is\s+no\s+longer\s+available",
    r"position\s+has\s+been\s+filled",
    r"requisition\s+has\s+closed",
    r"job\s+(?:expired|has\s+expired)",
    r"posting\s+has\s+expired",
]

# Keywords / selectors indicating a login wall or account creation gate
LOGIN_PATTERNS = [
    r"sign\s+in\s+to\s+apply",
    r"log\s+in\s+to\s+apply",
    r"create\s+(?:an\s+)?account\s+to\s+apply",
    r"sign\s+in\s+with\s+(?:google|linkedin|sso)",
    r"log\s+in\s+to\s+workday",
]

APPLY_BUTTON_SELECTORS = [
    'a:has-text("Apply")',
    'button:has-text("Apply")',
    'a:has-text("Apply Now")',
    'button:has-text("Apply Now")',
    'a:has-text("Apply for this job")',
    'button:has-text("Apply for this job")',
    'a:has-text("Start Application")',
    'button:has-text("Start Application")',
    '[data-automation-id*="apply"]',
    'a[href*="/apply"]',
    'a[href*="apply."]',
]


def classify_page(page: Page, url: str) -> TriageResult:
    """
    Evaluates an active Playwright page to classify its triage status.
    """
    try:
        page_title = page.title() or ""
        body_text = page.inner_text("body") or ""
    except Exception as e:
        logger.warning("Failed to read page text from %s: %s", url, e)
        return TriageResult(
            url=url,
            status=TriageStatus.DEAD,
            confidence=1.0,
            reason=f"Failed to access page body: {e}",
            actionable=False,
        )

    # 1. Check for CLOSED notices
    for pattern in CLOSED_PATTERNS:
        if re.search(pattern, body_text, re.IGNORECASE):
            match_str = re.search(pattern, body_text, re.IGNORECASE).group(0)
            return TriageResult(
                url=url,
                status=TriageStatus.CLOSED,
                confidence=0.98,
                reason=f"Posting is closed ('{match_str}')",
                actionable=False,
            )

    # 2. Check for LOGIN_WALL
    has_password_field = page.locator('input[type="password"]').count() > 0
    login_text_match = any(re.search(p, body_text, re.IGNORECASE) for p in LOGIN_PATTERNS)

    # Check whether application form fields exist
    candidate_input_count = page.locator(
        'input[type="text"], input[type="email"], input[type="tel"], textarea, input[type="file"]'
    ).count()

    if has_password_field and candidate_input_count <= 2:
        return TriageResult(
            url=url,
            status=TriageStatus.LOGIN_WALL,
            confidence=0.95,
            reason="Login or account creation wall detected",
            actionable=False,
        )

    if login_text_match and candidate_input_count == 0:
        return TriageResult(
            url=url,
            status=TriageStatus.LOGIN_WALL,
            confidence=0.90,
            reason="Sign-in prompt detected before application access",
            actionable=False,
        )

    # 3. Check for fillable FORM
    # If the page already has typical application form inputs
    has_email = page.locator('input[type="email"], input[name*="email" i], input[id*="email" i]').count() > 0
    has_name = page.locator('input[name*="name" i], input[id*="name" i]').count() > 0
    has_resume = page.locator('input[type="file"], input[name*="resume" i], input[id*="resume" i]').count() > 0

    if candidate_input_count >= 3 and (has_email or has_name or has_resume):
        return TriageResult(
            url=url,
            status=TriageStatus.FORM,
            confidence=0.95,
            reason=f"Interactive form detected ({candidate_input_count} input fields)",
            actionable=True,
        )

    # 4. Check for LANDING_PAGE with an Apply button
    for sel in APPLY_BUTTON_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                href = loc.get_attribute("href")
                return TriageResult(
                    url=url,
                    status=TriageStatus.LANDING_PAGE,
                    confidence=0.92,
                    reason=f"Job landing page with '{sel}' button",
                    apply_button_selector=sel,
                    apply_destination_url=href,
                    actionable=True,
                )
        except Exception:
            continue

    # 5. Fallback classification
    if candidate_input_count > 0:
        return TriageResult(
            url=url,
            status=TriageStatus.FORM,
            confidence=0.75,
            reason=f"Partial form detected ({candidate_input_count} fields)",
            actionable=True,
        )

    return TriageResult(
        url=url,
        status=TriageStatus.DEAD,
        confidence=0.70,
        reason="Page lacks both application form inputs and Apply buttons",
        actionable=False,
    )
