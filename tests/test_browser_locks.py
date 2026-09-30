"""Tests verifying that form submission is physically and architecturally impossible during the fill phase.

Enforces Hard Requirement 1:
1. Capture-phase 'submit' listener calls preventDefault().
2. Direct form.submit() and form.requestSubmit() throw security errors.
3. During fill phase, non-GET requests are unconditionally aborted by FillRouteGuard.
4. The fill module refuses to expose or interact with submit-type elements.
5. Verification that a test attempting to submit during the fill phase FAILS.
"""

from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

from qr_form_agent.browser.context import create_isolated_context
from qr_form_agent.fill.filler import FillItem, is_forbidden_submit_element, populate_single_field
from qr_form_agent.fill.route_guard import FillRouteGuard
from qr_form_agent.fill.snapshot import compute_snapshot_hash, extract_live_form_values

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "forms"


@pytest.fixture(scope="module")
def browser_env():
    with sync_playwright() as p:
        browser, context = create_isolated_context(p, headless=True, inject_locks=True)
        yield browser, context
        context.close()
        browser.close()


def test_capture_phase_submit_event_prevented(browser_env):
    """Verifies that dispatching a submit event is stopped by capture preventDefault()."""
    _, context = browser_env
    page = context.new_page()
    form_file = FIXTURES_DIR / "01_standard_job.html"
    page.goto(form_file.as_uri())

    # Dispatch submit event
    res = page.evaluate("""
        (() => {
            const form = document.querySelector('form');
            const evt = new Event('submit', { cancelable: true, bubbles: true });
            const dispatched = form.dispatchEvent(evt);
            return {
                dispatched: dispatched,
                defaultPrevented: evt.defaultPrevented,
                blockedCount: window.__QR_AGENT_BLOCKED_SUBMITS__
            };
        })()
    """)

    assert res["defaultPrevented"] is True, "Submit event must be preventDefault()'ed!"
    assert res["blockedCount"] >= 1, "Blocked submit counter must have incremented!"
    page.close()


def test_form_submit_prototype_throws_security_error(browser_env):
    """Verifies that programmatic form.submit() calls are blocked and throw errors."""
    _, context = browser_env
    page = context.new_page()
    form_file = FIXTURES_DIR / "01_standard_job.html"
    page.goto(form_file.as_uri())

    with pytest.raises(Exception) as exc_info:
        page.evaluate("document.querySelector('form').submit()")

    assert "Form submission blocked by QR Form Agent security lock" in str(exc_info.value)
    page.close()


def test_form_request_submit_prototype_throws_security_error(browser_env):
    """Verifies that programmatic form.requestSubmit() calls are blocked and throw errors."""
    _, context = browser_env
    page = context.new_page()
    form_file = FIXTURES_DIR / "01_standard_job.html"
    page.goto(form_file.as_uri())

    with pytest.raises(Exception) as exc_info:
        page.evaluate("document.querySelector('form').requestSubmit()")

    assert "blocked by QR Form Agent security lock" in str(exc_info.value)
    page.close()


def test_submit_button_click_blocked_and_fails_navigation(browser_env):
    """Verifies that clicking the submit button on a valid form does NOT navigate away or submit."""
    _, context = browser_env
    page = context.new_page()
    form_file = FIXTURES_DIR / "01_standard_job.html"
    page.goto(form_file.as_uri())
    original_url = page.url

    # Populate required fields so HTML5 browser validation allows submit event to dispatch
    page.fill("#first_name", "Alex")
    page.fill("#last_name", "Morgan")
    page.fill("#email", "alex@example.com")

    # Click the submit button directly
    page.click("#submit-btn")
    page.wait_for_timeout(300)

    # Invariant: Page URL must NOT have changed to the form action URL!
    assert page.url == original_url
    # Counter must be recorded
    blocked_count = page.evaluate("window.__QR_AGENT_BLOCKED_SUBMITS__")
    assert blocked_count >= 1
    page.close()


def test_route_guard_aborts_non_get_requests(browser_env):
    """Verifies that during fill phase, non-GET mutations to form action endpoints are aborted."""
    _, context = browser_env
    page = context.new_page()

    # Install FillRouteGuard first
    guard = FillRouteGuard(page)
    guard.install()

    # Load 15_ajax_submit_form.html content directly
    form_html = (FIXTURES_DIR / "15_ajax_submit_form.html").read_text(encoding="utf-8")
    page.set_content(form_html)

    # Register the fixture's form action endpoint so the guard knows to block it
    guard.register_form_action("https://example.com/api/ajax-apply")

    # Attempt fetch POST
    page.click("#ajax-submit-btn")
    page.wait_for_timeout(400)

    assert len(guard.blocked_requests) >= 1
    blocked = guard.blocked_requests[0]
    assert blocked.method == "POST"
    assert "form action endpoint" in blocked.reason or "aborted during form fill phase" in blocked.reason

    guard.uninstall()
    page.close()


def test_filler_module_refuses_submit_elements(browser_env):
    """Verifies that the fill module raises PermissionError if passed a submit element."""
    _, context = browser_env
    page = context.new_page()
    form_file = FIXTURES_DIR / "01_standard_job.html"
    page.goto(form_file.as_uri())

    loc = page.locator("#submit-btn")
    assert is_forbidden_submit_element(loc) is True

    item = FillItem(
        field_id="submit_btn",
        selector="#submit-btn",
        value="Malicious Submit Click",
    )

    with pytest.raises(PermissionError) as exc_info:
        populate_single_field(page, item)

    assert "Security invariant violated" in str(exc_info.value)
    page.close()


def test_snapshot_hash_deterministic_and_sensitive(browser_env):
    """Verifies SHA-256 snapshot hash determinism and sensitivity to modifications."""
    v1 = {"first_name": "Alice", "last_name": "Smith", "email": "alice@example.com"}
    v2 = {"email": "alice@example.com", "first_name": "Alice", "last_name": "Smith"}
    # Determinism despite key order
    assert compute_snapshot_hash(v1) == compute_snapshot_hash(v2)

    # Any modification changes hash
    v3 = {"first_name": "Alice", "last_name": "Smith", "email": "bob@example.com"}
    assert compute_snapshot_hash(v1) != compute_snapshot_hash(v3)
