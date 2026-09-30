"""Tests for Saved Answers Bank and LLM Bypass.

Enforces Requirement 9:
- Common recurring questions (visa sponsorship, notice period, relocation, salary)
  are answered deterministically from a saved answers bank.
- Matched answers completely bypass the LLM path at 1.0 confidence.
"""

from pathlib import Path
from unittest.mock import patch
import pytest

from qr_form_agent.browser.dom_extractor import FormFieldDescriptor
from qr_form_agent.mapping.engine import MappingEngine
from qr_form_agent.profile.answers_bank import AnswersBank, SavedAnswer
from qr_form_agent.profile.schema import Profile


def test_default_answers_bank_matches():
    """Default bank accurately resolves standard career questions at 1.0 confidence."""
    bank = AnswersBank()

    # Visa sponsorship
    m_sponsorship = bank.find_answer("Will you now or in the future require visa sponsorship?")
    assert m_sponsorship is not None
    assert m_sponsorship[0] == "visa_sponsorship"
    assert m_sponsorship[1] == "No"
    assert m_sponsorship[2] == 1.0

    # Notice period
    m_notice = bank.find_answer("What is your current notice period?")
    assert m_notice is not None
    assert m_notice[0] == "notice_period"
    assert m_notice[2] == 1.0

    # Relocation
    m_reloc = bank.find_answer("Are you willing to relocate for this position?")
    assert m_reloc is not None
    assert m_reloc[0] == "willing_to_relocate"
    assert m_reloc[1] == "Yes"

    # Salary expectation
    m_sal = bank.find_answer("Please state your salary expectations / desired compensation")
    assert m_sal is not None
    assert m_sal[0] == "salary_expectation"


def test_answers_bank_crud_and_persistence(tmp_path: Path):
    """Answers can be created, updated, saved to disk, and reloaded."""
    store_file = tmp_path / "custom_answers.json"
    bank = AnswersBank(storage_path=store_file)

    # Add custom answer
    bank.upsert_answer(
        key="security_clearance",
        question_text="Do you hold active government security clearance?",
        value="Yes (SC Cleared)",
        category="legal",
        match_patterns=[r"security\s+clearance", r"sc\s+cleared", r"dv\s+cleared"],
    )

    # Verify query
    match = bank.find_answer("Do you have active security clearance?")
    assert match is not None
    assert match[0] == "security_clearance"
    assert match[1] == "Yes (SC Cleared)"

    # Reload from disk into new instance
    reloaded_bank = AnswersBank(storage_path=store_file)
    assert reloaded_bank.get_answer("security_clearance") is not None
    match_reloaded = reloaded_bank.find_answer("Do you have SC cleared status?")
    assert match_reloaded is not None
    assert match_reloaded[1] == "Yes (SC Cleared)"

    # Delete
    assert reloaded_bank.delete_answer("security_clearance") is True
    assert reloaded_bank.get_answer("security_clearance") is None


def test_mapping_engine_bypasses_llm_for_answers_bank_match():
    """Fields matching the answers bank bypass LLM mapping and receive 1.0 confidence."""
    profile = Profile(
        full_name="Alex Morgan",
        email="alex.morgan@example.com",
    )

    bank = AnswersBank()
    engine = MappingEngine(answers_bank=bank)

    field = FormFieldDescriptor(
        field_id="f_sponsorship",
        tag_name="input",
        field_type="text",
        name="visa_sponsorship_needed",
        label="Do you require visa sponsorship for employment?",
        selector="#f_sponsorship",
    )

    with patch("qr_form_agent.mapping.engine.map_fields_with_llm") as mock_llm:
        res = engine.process_form_fields(
            url="https://careers.example.com/apply",
            fields=[field],
            profile=profile,
        )

        # LLM must NOT be called for fields resolved by the bank
        mock_llm.assert_not_called()

        assert len(res.mapped_fields) == 1
        mf = res.mapped_fields[0]
        assert mf.profile_key == "answers_bank.visa_sponsorship"
        assert mf.value == "No"
        assert mf.confidence == 1.0
        assert "Answers Bank" in mf.reason
