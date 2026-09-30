"""Tests for Page Triage, Classification, Apply Hopper, and Reporting.

Enforces Requirements 1 & 2:
1. Decode every QR, fetch URL, and classify as FORM, LANDING_PAGE, LOGIN_WALL, CLOSED, DEAD.
2. Follow 'Apply' button on landing pages via SSRF-safe gate.
"""

from unittest.mock import MagicMock, patch
import pytest
from playwright.sync_api import sync_playwright

from qr_form_agent.safety.url_gate import ValidationResult
from qr_form_agent.triage.classifier import classify_page
from qr_form_agent.triage.landing_hopper import follow_apply_button
from qr_form_agent.triage.models import TriageResult, TriageStatus
from qr_form_agent.triage.report import generate_triage_table, summarize_triage


@pytest.fixture(scope="module")
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        page.close()
        browser.close()


def test_classify_form_page(browser_page):
    """Page with standard application inputs must be classified as FORM."""
    html = """
    <html>
      <body>
        <h1>Software Engineer Application</h1>
        <form>
          <input type="text" name="full_name" placeholder="Full Name" />
          <input type="email" name="email" placeholder="Email" />
          <input type="tel" name="phone" placeholder="Phone" />
          <textarea name="cover_letter"></textarea>
        </form>
      </body>
    </html>
    """
    browser_page.set_content(html)
    res = classify_page(browser_page, "https://jobs.example.com/apply")

    assert res.status == TriageStatus.FORM
    assert res.actionable is True
    assert res.confidence >= 0.90


def test_classify_closed_page(browser_page):
    """Page with 'applications are closed' text must be classified as CLOSED."""
    html = """
    <html>
      <body>
        <h1>Graduate Analyst Programme</h1>
        <div class="banner">
          <p>Thank you for your interest. Applications are closed for this cohort.</p>
        </div>
      </body>
    </html>
    """
    browser_page.set_content(html)
    res = classify_page(browser_page, "https://jobs.example.com/grad")

    assert res.status == TriageStatus.CLOSED
    assert res.actionable is False
    assert "closed" in res.reason.lower()


def test_classify_login_wall(browser_page):
    """Page requiring login/password with no application inputs must be LOGIN_WALL."""
    html = """
    <html>
      <body>
        <h1>Workday Sign In</h1>
        <p>Sign in to apply for this job</p>
        <form action="/login">
          <input type="text" name="username" />
          <input type="password" name="password" />
          <button type="submit">Sign In</button>
        </form>
      </body>
    </html>
    """
    browser_page.set_content(html)
    res = classify_page(browser_page, "https://myworkdayjobs.com/login")

    assert res.status == TriageStatus.LOGIN_WALL
    assert res.actionable is False


def test_classify_landing_page(browser_page):
    """Page with job description and an Apply link must be LANDING_PAGE."""
    html = """
    <html>
      <body>
        <h1>Senior Python Developer</h1>
        <p>Join our core engineering team to build high scale tools.</p>
        <a href="https://jobs.example.com/roles/123/apply" class="btn">Apply Now</a>
      </body>
    </html>
    """
    browser_page.set_content(html)
    res = classify_page(browser_page, "https://jobs.example.com/roles/123")

    assert res.status == TriageStatus.LANDING_PAGE
    assert res.actionable is True
    assert res.apply_button_selector is not None
    assert "https://jobs.example.com/roles/123/apply" in (res.apply_destination_url or "")


def test_classify_dead_page(browser_page):
    """Page without job content, inputs, or apply links must be DEAD."""
    html = """
    <html>
      <body>
        <h1>404 Not Found</h1>
        <p>The page you requested does not exist.</p>
      </body>
    </html>
    """
    browser_page.set_content(html)
    res = classify_page(browser_page, "https://jobs.example.com/missing")

    assert res.status == TriageStatus.DEAD
    assert res.actionable is False


def test_follow_apply_button_blocks_ssrf(browser_page):
    """Landing hopper must reject destination links to private IPs (SSRF)."""
    landing_result = TriageResult(
        url="https://careers.example.com/job",
        status=TriageStatus.LANDING_PAGE,
        confidence=0.9,
        reason="Has apply button",
        apply_button_selector='a:has-text("Apply")',
        apply_destination_url="http://169.254.169.254/latest/meta-data",
        actionable=True,
    )

    success, dest_url, new_res, msg = follow_apply_button(
        browser_page, landing_result, base_url="https://careers.example.com/job"
    )

    assert success is False
    assert "SSRF" in msg or "Safety" in msg


def test_follow_apply_button_valid_navigation(browser_page):
    """Landing hopper successfully validates and navigates to safe URL."""
    landing_result = TriageResult(
        url="https://careers.example.com/job",
        status=TriageStatus.LANDING_PAGE,
        confidence=0.9,
        reason="Has apply button",
        apply_button_selector='a:has-text("Apply")',
        apply_destination_url="https://careers.example.com/job/apply",
        actionable=True,
    )

    with patch("qr_form_agent.triage.landing_hopper.validate_url") as mock_val:
        mock_val.return_value = ValidationResult(
            is_safe=True,
            final_url="https://careers.example.com/job/apply",
        )
        with patch.object(browser_page, "goto") as mock_goto:
            with patch("qr_form_agent.triage.landing_hopper.classify_page") as mock_cls:
                mock_cls.return_value = TriageResult(
                    url="https://careers.example.com/job/apply",
                    status=TriageStatus.FORM,
                    confidence=0.95,
                    reason="Interactive form",
                    actionable=True,
                )

                success, dest_url, new_res, msg = follow_apply_button(
                    browser_page, landing_result, base_url="https://careers.example.com/job"
                )

                assert success is True
                assert dest_url == "https://careers.example.com/job/apply"
                assert new_res.status == TriageStatus.FORM
                mock_goto.assert_called_once()


def test_triage_reporting_table():
    """Generates triage table and summary metrics cleanly."""
    results = [
        TriageResult(url="https://a.com", status=TriageStatus.FORM, confidence=0.9, reason="Form ok", actionable=True, company="Acme"),
        TriageResult(url="https://b.com", status=TriageStatus.CLOSED, confidence=0.95, reason="Closed", actionable=False, company="Beta"),
        TriageResult(url="https://c.com", status=TriageStatus.LANDING_PAGE, confidence=0.92, reason="Apply btn", actionable=True, company="Gamma"),
    ]

    table = generate_triage_table(results)
    assert table is not None
    assert len(table.rows) == 3

    summary = summarize_triage(results)
    assert summary["total"] == 3
    assert summary["actionable"] == 2
    assert summary["counts"]["FORM"] == 1
    assert summary["counts"]["CLOSED"] == 1
    assert summary["counts"]["LANDING_PAGE"] == 1
