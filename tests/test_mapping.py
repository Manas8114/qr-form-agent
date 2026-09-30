"""Tests for mapping accuracy, fail-closed denylist enforcement, and domain caching across 15 fixtures."""

from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

from qr_form_agent.browser.context import create_isolated_context
from qr_form_agent.browser.dom_extractor import extract_form_dom
from qr_form_agent.mapping.cache import MappingCache
from qr_form_agent.mapping.engine import MappingEngine
from qr_form_agent.profile.schema import Profile

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "forms"


@pytest.fixture(scope="module")
def browser_env():
    with sync_playwright() as p:
        browser, context = create_isolated_context(p, headless=True, inject_locks=True)
        yield browser, context
        context.close()
        browser.close()


@pytest.fixture
def sample_profile():
    return Profile(
        full_name="Alex Morgan",
        first_name="Alex",
        last_name="Morgan",
        email="alex.morgan@example.com",
        phone="555-123-4567",
        address="100 Innovation Way",
        city="San Francisco",
        state="CA",
        postal_code="94105",
        country="US",
        linkedin_url="https://linkedin.com/in/alex-morgan",
        github_url="https://github.com/alexmorgan",
        portfolio_url="https://alexmorgan.dev",
        summary="Experienced Full-Stack Software Engineer specializing in Python.",
        skills=["Python", "FastAPI", "Playwright", "Docker"],
        resume_file_path=str(Path("./test_resume.pdf").resolve()),
    )


def test_standard_job_application_mapping(browser_env, sample_profile):
    """Fixture 01: Standard job application mapping accuracy."""
    _, context = browser_env
    page = context.new_page()
    page.goto((FIXTURES_DIR / "01_standard_job.html").as_uri())

    dom = extract_form_dom(page)
    engine = MappingEngine()
    result = engine.process_form_fields(page.url, dom.fields, sample_profile)

    assert result.has_denylisted_fields is False
    assert len(result.mapped_fields) == 5

    field_map = {m.field_id: m for m in result.mapped_fields}
    assert field_map["first_name"].value == "Alex"
    assert field_map["last_name"].value == "Morgan"
    assert field_map["email"].value == "alex.morgan@example.com"
    assert field_map["phone"].value == "555-123-4567"
    assert field_map["resume"].is_resume_upload is True
    page.close()


def test_autocomplete_attributes_mapping(browser_env, sample_profile):
    """Fixture 02: Autocomplete attributes mapping accuracy."""
    _, context = browser_env
    page = context.new_page()
    page.goto((FIXTURES_DIR / "02_autocomplete_attrs.html").as_uri())

    dom = extract_form_dom(page)
    engine = MappingEngine()
    result = engine.process_form_fields(page.url, dom.fields, sample_profile)

    assert result.has_denylisted_fields is False
    field_map = {m.field_id: m for m in result.mapped_fields}
    assert field_map["fn"].value == "Alex"
    assert field_map["ln"].value == "Morgan"
    assert field_map["em"].value == "alex.morgan@example.com"
    assert field_map["ph"].value == "555-123-4567"
    assert field_map["addr"].value == "100 Innovation Way"
    assert field_map["cty"].value == "San Francisco"
    assert field_map["zip"].value == "94105"
    page.close()


def test_obscure_labels_mapping(browser_env, sample_profile):
    """Fixture 03: Obscure label structures."""
    _, context = browser_env
    page = context.new_page()
    page.goto((FIXTURES_DIR / "03_obscure_labels.html").as_uri())

    dom = extract_form_dom(page)
    engine = MappingEngine()
    result = engine.process_form_fields(page.url, dom.fields, sample_profile)

    field_map = {m.field_id: m for m in result.mapped_fields}
    assert field_map["cand_name"].value == "Alex Morgan"
    assert field_map["c_email"].value == "alex.morgan@example.com"
    assert field_map["li_link"].value == "https://linkedin.com/in/alex-morgan"
    assert field_map["mobile_no"].value == "555-123-4567"
    page.close()


def test_denylist_password_fails_closed(browser_env, sample_profile):
    """Fixture 06: Form containing password must trigger denylist and fail closed."""
    _, context = browser_env
    page = context.new_page()
    page.goto((FIXTURES_DIR / "06_denylist_password.html").as_uri())

    dom = extract_form_dom(page)
    engine = MappingEngine()
    result = engine.process_form_fields(page.url, dom.fields, sample_profile)

    assert result.has_denylisted_fields is True
    assert result.needs_human is True
    assert any("password" in r.lower() for r in result.denylist_reasons)
    page.close()


def test_denylist_ssn_fails_closed(browser_env, sample_profile):
    """Fixture 07: Form asking for SSN must trigger denylist."""
    _, context = browser_env
    page = context.new_page()
    page.goto((FIXTURES_DIR / "07_denylist_ssn.html").as_uri())

    dom = extract_form_dom(page)
    engine = MappingEngine()
    result = engine.process_form_fields(page.url, dom.fields, sample_profile)

    assert result.has_denylisted_fields is True
    assert result.needs_human is True
    assert any("ssn" in r.lower() or "government" in r.lower() for r in result.denylist_reasons)
    page.close()


def test_denylist_payment_fails_closed(browser_env, sample_profile):
    """Fixture 08: Form asking for credit card must trigger denylist."""
    _, context = browser_env
    page = context.new_page()
    page.goto((FIXTURES_DIR / "08_denylist_payment.html").as_uri())

    dom = extract_form_dom(page)
    engine = MappingEngine()
    result = engine.process_form_fields(page.url, dom.fields, sample_profile)

    assert result.has_denylisted_fields is True
    assert result.needs_human is True
    assert any("payment" in r.lower() for r in result.denylist_reasons)
    page.close()


def test_domain_mapping_cache(tmp_path: Path, sample_profile):
    """Verifies SQLite cache stores and retrieves approved domain mappings."""
    db_file = tmp_path / "cache_test.db"
    cache = MappingCache(db_path=db_file)

    sig = cache.compute_field_signature("input", "text", "applicant_phone_custom", "Cellular Direct Line")
    cache.record_approved_mapping("custom-portal.test", sig, "phone")

    cached_key = cache.get_cached_key("custom-portal.test", sig)
    assert cached_key == "phone"

    # Mismatch domain returns None
    assert cache.get_cached_key("other-portal.test", sig) is None
