"""Tests for ATS platform adapters (Workday, Greenhouse, Lever, CoreHR).

Enforces Requirement 4 & 16:
- Specialized field mapping for the four major ATS platforms.
- High-confidence field mapping against recorded real forms.
"""

from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

from qr_form_agent.adapters.corehr import CoreHRAdapter
from qr_form_agent.adapters.greenhouse import GreenhouseAdapter
from qr_form_agent.adapters.lever import LeverAdapter
from qr_form_agent.adapters.registry import AdapterRegistry
from qr_form_agent.adapters.workday import WorkdayAdapter
from qr_form_agent.browser.dom_extractor import extract_form_dom, FormFieldDescriptor
from qr_form_agent.profile.answers_bank import AnswersBank
from qr_form_agent.profile.schema import ExperienceItem, Profile

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "forms"


@pytest.fixture(scope="module")
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        page.close()
        browser.close()


@pytest.fixture
def candidate_profile():
    return Profile(
        full_name="Alex Morgan",
        first_name="Alex",
        last_name="Morgan",
        email="alex.morgan@example.com",
        phone="+44 7123 456789",
        linkedin_url="https://linkedin.com/in/alexmorgan",
        github_url="https://github.com/alexmorgan",
        city="London",
        address="10 Downing Street",
        postal_code="SW1A 2AA",
        requires_sponsorship=False,
        experience=[
            ExperienceItem(
                company="Tech Solutions Ltd",
                title="Senior Software Engineer",
                is_current=True,
            )
        ],
    )


def test_adapter_registry_selection():
    """Registry correctly identifies platform from URL or HTML hints."""
    registry = AdapterRegistry()

    # Greenhouse
    gh = registry.find_adapter("https://boards.greenhouse.io/twitch/jobs/456")
    assert gh is not None
    assert gh.name == "greenhouse"

    # Lever
    lv = registry.find_adapter("https://jobs.lever.co/stripe/789")
    assert lv is not None
    assert lv.name == "lever"

    # Workday
    wd = registry.find_adapter("https://target.myworkdayjobs.com/en-US/careers/job/123")
    assert wd is not None
    assert wd.name == "workday"

    # CoreHR
    core = registry.find_adapter("https://corehr.com/recruitment/apply", html="<div class='corehr'></div>")
    assert core is not None
    assert core.name == "corehr"


def test_greenhouse_adapter_mapping(browser_page, candidate_profile):
    """Greenhouse adapter maps all required fields from real greenhouse form."""
    form_path = FIXTURES_DIR / "16_greenhouse_real.html"
    browser_page.goto(form_path.as_uri())

    fields = extract_form_dom(browser_page).fields
    adapter = GreenhouseAdapter()
    answers = AnswersBank()

    mapped = adapter.map_fields(fields, candidate_profile, answers)
    mapped_dict = {m.profile_key: m for m in mapped if m.profile_key}

    assert "first_name" in mapped_dict
    assert mapped_dict["first_name"].value == "Alex"
    assert mapped_dict["first_name"].confidence >= 0.95

    assert "last_name" in mapped_dict
    assert mapped_dict["last_name"].value == "Morgan"

    assert "email" in mapped_dict
    assert mapped_dict["email"].value == "alex.morgan@example.com"

    assert "phone" in mapped_dict
    assert mapped_dict["phone"].value == "+44 7123 456789"

    assert "linkedin_url" in mapped_dict
    assert mapped_dict["linkedin_url"].value == "https://linkedin.com/in/alexmorgan"

    # Answers bank sponsorship match
    sponsorship_matches = [m for m in mapped if "sponsorship" in (m.reason or "").lower()]
    assert len(sponsorship_matches) >= 1
    assert sponsorship_matches[0].confidence == 1.0


def test_workday_adapter_mapping(browser_page, candidate_profile):
    """Workday adapter detects data-automation-id attributes on real Workday form."""
    form_path = FIXTURES_DIR / "17_workday_real.html"
    browser_page.goto(form_path.as_uri())

    fields = extract_form_dom(browser_page).fields
    adapter = WorkdayAdapter()
    answers = AnswersBank()

    mapped = adapter.map_fields(fields, candidate_profile, answers)
    mapped_dict = {m.profile_key: m for m in mapped if m.profile_key}

    assert "first_name" in mapped_dict
    assert mapped_dict["first_name"].value == "Alex"
    assert mapped_dict["first_name"].confidence >= 0.95

    assert "last_name" in mapped_dict
    assert mapped_dict["last_name"].value == "Morgan"

    assert "email" in mapped_dict
    assert mapped_dict["email"].value == "alex.morgan@example.com"

    assert "city" in mapped_dict
    assert mapped_dict["city"].value == "London"

    # Notice period from answers bank
    notice_matches = [m for m in mapped if "notice" in (m.reason or "").lower()]
    assert len(notice_matches) >= 1
    assert notice_matches[0].confidence == 1.0


def test_lever_adapter_mapping(browser_page, candidate_profile):
    """Lever adapter maps full name, org, urls, and relocation from real Lever form."""
    form_path = FIXTURES_DIR / "18_lever_real.html"
    browser_page.goto(form_path.as_uri())

    fields = extract_form_dom(browser_page).fields
    adapter = LeverAdapter()
    answers = AnswersBank()

    mapped = adapter.map_fields(fields, candidate_profile, answers)
    mapped_dict = {m.profile_key: m for m in mapped if m.profile_key}

    assert "full_name" in mapped_dict
    assert mapped_dict["full_name"].value == "Alex Morgan"

    assert "email" in mapped_dict
    assert mapped_dict["email"].value == "alex.morgan@example.com"

    assert "linkedin_url" in mapped_dict
    assert mapped_dict["linkedin_url"].value == "https://linkedin.com/in/alexmorgan"

    assert "github_url" in mapped_dict
    assert mapped_dict["github_url"].value == "https://github.com/alexmorgan"

    assert "current_company" in mapped_dict
    assert mapped_dict["current_company"].value == "Tech Solutions Ltd"

    # Answers bank relocation match
    reloc_matches = [m for m in mapped if "relocat" in (m.reason or "").lower() or "relocate" in (m.profile_key or "").lower()]
    assert len(reloc_matches) >= 1
    assert reloc_matches[0].confidence == 1.0


def test_corehr_adapter_mapping(candidate_profile):
    """CoreHR adapter handles typical enterprise txt_forename and txt_surname fields."""
    fields = [
        FormFieldDescriptor(field_id="txt_forename", name="txt_forename", label="Forename(s)", tag_name="input", field_type="text", selector="#txt_forename"),
        FormFieldDescriptor(field_id="txt_surname", name="txt_surname", label="Surname", tag_name="input", field_type="text", selector="#txt_surname"),
        FormFieldDescriptor(field_id="txt_email", name="txt_email", label="Email Address", tag_name="input", field_type="email", selector="#txt_email"),
        FormFieldDescriptor(field_id="txt_mobile", name="txt_mobile", label="Mobile Telephone", tag_name="input", field_type="tel", selector="#txt_mobile"),
    ]

    adapter = CoreHRAdapter()
    mapped = adapter.map_fields(fields, candidate_profile)
    mapped_dict = {m.profile_key: m for m in mapped if m.profile_key}

    assert mapped_dict["first_name"].value == "Alex"
    assert mapped_dict["last_name"].value == "Morgan"
    assert mapped_dict["email"].value == "alex.morgan@example.com"
    assert mapped_dict["phone"].value == "+44 7123 456789"
