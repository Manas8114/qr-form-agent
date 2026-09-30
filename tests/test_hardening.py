"""Tests for Route-level Hardening, Pinned DNS SSRF Checks, GET Submit Abortion, and Dry-Run Reporting.

Enforces Requirements 14 & 15:
- Route-level SSRF checks with pinned DNS resolution.
- Strict blocking of GET form submissions.
- Neutralization of programmatic form.submit().
- Dry-run report generation of fields filled vs refused.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from playwright.sync_api import sync_playwright

from qr_form_agent.browser.context import create_isolated_context
from qr_form_agent.fill.dry_run_report import build_dry_run_report
from qr_form_agent.fill.route_guard import FillRouteGuard
from qr_form_agent.mapping.tier1_rules import MappedField

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "forms"


@pytest.fixture(scope="module")
def browser_env():
    with sync_playwright() as p:
        browser, context = create_isolated_context(p, headless=True, inject_locks=True)
        yield browser, context
        context.close()
        browser.close()


def test_route_guard_blocks_ssrf_via_pinned_dns(browser_env):
    """Route guard detects and aborts requests to hostnames resolving to private IPs."""
    _, context = browser_env
    page = context.new_page()

    guard = FillRouteGuard(page)
    guard.install()

    # Mock host resolution to return private SSRF IP
    with patch("qr_form_agent.fill.route_guard.resolve_and_check_host") as mock_dns:
        mock_dns.return_value = (False, "SSRF attempt: resolves to private IP 10.0.0.1", ["10.0.0.1"])

        with pytest.raises(Exception):
            # Attempt to navigate to malicious host
            page.goto("https://internal-portal.evil.com/admin", timeout=3000)

        # Confirm request was recorded in blocked list
        assert len(guard.blocked_requests) >= 1
        blocked = guard.blocked_requests[0]
        assert "Route-level SSRF check failed" in blocked.reason

    guard.uninstall()
    page.close()


def test_route_guard_blocks_mutating_methods(browser_env):
    """Mutating methods (POST/PUT/DELETE) are unconditionally aborted during fill phase."""
    _, context = browser_env
    page = context.new_page()
    form_file = FIXTURES_DIR / "01_standard_job.html"
    page.goto(form_file.as_uri())

    guard = FillRouteGuard(page, allow_local_for_testing=True)
    guard.install()

    # Trigger a fetch POST request to external https endpoint
    page.evaluate("""
        async () => {
            try {
                await fetch('https://example.com/api/submit', {
                    method: 'POST',
                    body: JSON.stringify({ name: 'Alex' }),
                    headers: { 'Content-Type': 'application/json' }
                });
            } catch (e) {}
        }
    """)
    page.wait_for_timeout(200)

    assert len(guard.blocked_requests) >= 1
    post_block = [b for b in guard.blocked_requests if b.method == "POST"]
    assert len(post_block) >= 1
    assert "aborted during fill phase" in post_block[0].reason or "form action endpoint" in post_block[0].reason

    guard.uninstall()
    page.close()


def test_route_guard_blocks_get_form_submissions(browser_env):
    """GET requests carrying sensitive serialized form payloads are aborted."""
    _, context = browser_env
    page = context.new_page()

    guard = FillRouteGuard(page, allow_local_for_testing=True)
    guard.register_form_action("https://careers.example.com/apply/submit")
    guard.install()

    # Simulate GET submission to registered form action with query payload
    fake_req = MagicMock()
    fake_req.method = "GET"
    fake_req.url = "https://careers.example.com/apply/submit?first_name=Alex&email=alex@test.com"

    assert guard._is_get_form_submit(fake_req) is True

    # Regular harmless GET request
    safe_req = MagicMock()
    safe_req.method = "GET"
    safe_req.url = "https://careers.example.com/assets/styles.css"
    assert guard._is_get_form_submit(safe_req) is False

    guard.uninstall()
    page.close()


def test_programmatic_form_submit_neutralized(browser_env):
    """Direct form.submit() call throws security error and does not submit."""
    _, context = browser_env
    page = context.new_page()
    form_file = FIXTURES_DIR / "01_standard_job.html"
    page.goto(form_file.as_uri())

    res = page.evaluate("""
        (() => {
            const form = document.querySelector('form');
            try {
                form.submit();
                return { threw: false };
            } catch (err) {
                return { threw: true, message: err.message };
            }
        })()
    """)

    assert res["threw"] is True
    assert "SecurityError" in res["message"] or "Neutralized" in res["message"] or "blocked" in res["message"].lower()
    page.close()


def test_dry_run_report_generation():
    """Builds comprehensive audit report classifying fillable vs refused fields."""
    mapped_fields = [
        MappedField(
            field_id="first_name",
            selector="#first_name",
            profile_key="first_name",
            value="Alex",
            confidence=0.98,
            reason="Profile match",
        ),
        MappedField(
            field_id="email",
            selector="#email",
            profile_key="email",
            value="alex@example.com",
            confidence=0.99,
            reason="Profile match",
        ),
        MappedField(
            field_id="cvv",
            selector="#cvv",
            profile_key=None,
            value=None,
            confidence=0.0,
            reason="Denylisted financial field",
        ),
        MappedField(
            field_id="obscure_q",
            selector="#q4",
            profile_key=None,
            value=None,
            confidence=0.2,
            reason="Low confidence",
        ),
    ]

    report = build_dry_run_report(
        job_id="job_audit_1",
        url="https://jobs.example.com/grad",
        mapped_fields=mapped_fields,
        company="Stripe",
        role="Backend Engineer",
        blocked_submits_count=2,
    )

    assert report.job_id == "job_audit_1"
    assert report.company == "Stripe"
    assert len(report.fields_to_fill) == 2
    assert len(report.fields_refused) == 2
    assert report.submit_buttons_neutralized == 2
    assert report.overall_confidence > 0.90

    # Ensure rich table renders without errors
    table = report.to_rich_table()
    assert table is not None
    assert len(table.rows) == 4
