"""Tests for profile extraction, schema validation, null-fidelity, and storage."""

import json
from pathlib import Path
import pytest
import pymupdf as fitz

from qr_form_agent.profile.extractor import extract_text_from_pdf
from qr_form_agent.profile.schema import Profile, EducationItem, ExperienceItem
from qr_form_agent.profile.storage import load_verified_profile, save_verified_profile
from qr_form_agent.profile.synthesizer import _synthesize_heuristically


def _create_sample_pdf(tmp_path: Path) -> Path:
    """Creates a sample PDF resume for testing using PyMuPDF."""
    pdf_path = tmp_path / "sample_resume.pdf"
    doc = fitz.open()
    page = doc.new_page()

    text = """Alex Morgan
alex.morgan@example.com
(555) 234-5678
https://linkedin.com/in/alex-morgan
https://github.com/alexmorgan

Technical Skills: Python, TypeScript, Docker, Playwright, FastAPI

Experience:
Senior Software Engineer - Tech Solutions Inc (2021 - Present)
- Architected automated form processing agents.

Education:
University of California, Berkeley - B.S. Computer Science (2017 - 2021)
"""
    page.insert_text((50, 72), text, fontsize=11)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_pdf_text_extraction(tmp_path: Path):
    pdf_path = _create_sample_pdf(tmp_path)
    text = extract_text_from_pdf(pdf_path)

    assert "Alex Morgan" in text
    assert "alex.morgan@example.com" in text
    assert "Python, TypeScript" in text


def test_profile_schema_null_fidelity():
    """Ensure absent fields default to None and are not guessed."""
    p = Profile(
        full_name="Jane Doe",
        email="jane@example.com",
    )
    assert p.phone is None
    assert p.address is None
    assert p.postal_code is None
    assert p.work_authorization is None
    assert p.requires_sponsorship is None
    assert p.skills == []
    assert p.education == []


def test_heuristic_synthesis_accuracy():
    sample_text = """Johnathan Smith
jsmith@domain.org
(123) 456-7890
https://linkedin.com/in/johnsmith
https://github.com/johnsmith

Technical Skills: Python, SQL, Git, Linux
"""
    profile = _synthesize_heuristically(sample_text)

    assert profile.email == "jsmith@domain.org"
    assert profile.phone == "(123) 456-7890"
    assert profile.linkedin_url == "https://linkedin.com/in/johnsmith"
    assert profile.github_url == "https://github.com/johnsmith"
    assert "Python" in profile.skills
    assert "SQL" in profile.skills
    assert profile.full_name == "Johnathan Smith"
    # Unmentioned fields must remain strictly None
    assert profile.address is None
    assert profile.work_authorization is None


def test_profile_save_and_load(tmp_path: Path):
    profile_file = tmp_path / "verified_profile.json"
    p = Profile(
        full_name="Samantha Ray",
        first_name="Samantha",
        last_name="Ray",
        email="samantha@example.com",
        skills=["Python", "FastAPI"],
    )

    saved_path = save_verified_profile(p, profile_file)
    assert saved_path.exists()

    loaded = load_verified_profile(profile_file)
    assert loaded is not None
    assert loaded.full_name == "Samantha Ray"
    assert loaded.email == "samantha@example.com"
    assert loaded.skills == ["Python", "FastAPI"]
    assert loaded.phone is None  # Unset field stays None
