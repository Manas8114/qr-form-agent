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

Summary
Experienced full-stack engineer with 5 years of experience in building scalable web applications.

Technical Skills: Python, TypeScript, Docker, Playwright, FastAPI

Experience
Senior Software Engineer - Tech Solutions Inc (2021 - Present)
- Architected automated form processing agents.
- Reduced deployment time by 40% through CI/CD pipeline improvements.

Junior Developer - WebStart LLC (2019 - 2021)
- Built React frontends for client dashboards.

Education
University of California, Berkeley - B.S. Computer Science (2017 - 2021)
GPA: 3.8

Projects
QR Form Agent
- Automated career fair form filling with AI-powered field mapping.
- Tech stack: Python, Playwright, FastAPI
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

Skills
Python, SQL, Git, Linux
"""
    profile = _synthesize_heuristically(sample_text)

    assert profile.email == "jsmith@domain.org"
    assert profile.phone == "(123) 456-7890"
    assert profile.linkedin_url == "https://linkedin.com/in/johnsmith"
    assert profile.github_url == "https://github.com/johnsmith"
    assert "Python" in profile.skills
    assert "SQL" in profile.skills
    assert profile.full_name == "Johnathan Smith"
    assert profile.first_name == "Johnathan"
    assert profile.last_name == "Smith"
    # Unmentioned fields must remain strictly None
    assert profile.address is None
    assert profile.work_authorization is None


def test_heuristic_extracts_education():
    """Verify that the heuristic parser extracts education entries."""
    text = """Jane Doe
jane@test.com

Education
Stanford University - M.S. Computer Science (2020 - 2022)
GPA: 3.9

University of Texas at Austin - B.S. Electrical Engineering (2016 - 2020)
"""
    profile = _synthesize_heuristically(text)

    assert len(profile.education) >= 1
    # Check the first education entry has institution
    assert any("Stanford" in (e.institution or "") for e in profile.education)
    # Check degree extraction
    assert any(e.degree is not None for e in profile.education)


def test_heuristic_extracts_experience():
    """Verify that the heuristic parser extracts experience entries."""
    text = """Mark Johnson
mark@company.com

Experience
Lead Engineer - Google (Jan 2022 - Present)
- Built large-scale distributed systems
- Led a team of 8 engineers

Software Developer - Microsoft (Jun 2019 - Dec 2021)
- Developed Azure DevOps integrations
"""
    profile = _synthesize_heuristically(text)

    assert len(profile.experience) >= 1
    # Check that we got title and company
    has_google = any("Google" in (e.company or "") for e in profile.experience)
    assert has_google
    # Current role detection
    current_jobs = [e for e in profile.experience if e.is_current]
    assert len(current_jobs) >= 1


def test_heuristic_extracts_projects():
    """Verify that the heuristic parser extracts project entries."""
    text = """Alice Chen
alice@dev.com

Projects
OpenSource Dashboard
- A real-time metrics visualization tool for Kubernetes clusters
- Tech stack: React, Go, Grafana

ChatBot Assistant
- AI-powered chatbot using transformer models
"""
    profile = _synthesize_heuristically(text)

    assert len(profile.projects) >= 1
    assert any("Dashboard" in (p.name or "") for p in profile.projects)


def test_heuristic_splits_first_last_name():
    """Verify first/last name splitting works."""
    text = """Manas Sharma
test@email.com
"""
    profile = _synthesize_heuristically(text)

    assert profile.full_name == "Manas Sharma"
    assert profile.first_name == "Manas"
    assert profile.last_name == "Sharma"


def test_heuristic_extracts_summary():
    """Verify summary/objective extraction."""
    text = """Bob Smith
bob@test.com

Summary
Dedicated software engineer with 10 years of experience in backend development and cloud architecture.

Skills
Python, AWS, Docker
"""
    profile = _synthesize_heuristically(text)

    assert profile.summary is not None
    assert "software engineer" in profile.summary.lower()


def test_heuristic_extracts_inline_skills():
    """Verify inline skills extraction (no section header)."""
    text = """Test Person

Technical Skills: Python, JavaScript, React, Docker, Kubernetes
"""
    profile = _synthesize_heuristically(text)

    assert "Python" in profile.skills
    assert "React" in profile.skills


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


def test_comprehensive_resume_parsing():
    """Full resume integration test with all sections."""
    text = """Manas Sharma
manassharma8114@gmail.com
+91 98765 43210
https://linkedin.com/in/manas-sharma
https://github.com/Manas8114
Dalli Rajhara, Chhattisgarh, India

Summary
Passionate computer science student with strong skills in full-stack development and AI/ML.

Education
Sanjivani University - B.Tech Computer Science (2022 - 2026)
CGPA: 8.5

Experience
Software Intern - TechCorp (May 2024 - Aug 2024)
- Developed REST APIs using FastAPI and PostgreSQL
- Implemented CI/CD pipelines with GitHub Actions

Skills
Python, JavaScript, React, Node.js, FastAPI, Docker, Git, PostgreSQL, MongoDB

Projects
AI Resume Agent
- Built an intelligent agent for automated job applications
- Tech stack: Python, Playwright, FastAPI

E-Commerce Platform
- Full-stack web application with payment integration
- Built with: React, Node.js, MongoDB
"""
    profile = _synthesize_heuristically(text)

    # Contact info
    assert profile.full_name == "Manas Sharma"
    assert profile.first_name == "Manas"
    assert profile.last_name == "Sharma"
    assert profile.email == "manassharma8114@gmail.com"
    assert profile.phone is not None
    assert profile.linkedin_url is not None
    assert profile.github_url is not None

    # Location
    assert profile.country is not None

    # Summary
    assert profile.summary is not None

    # Education
    assert len(profile.education) >= 1

    # Experience
    assert len(profile.experience) >= 1

    # Skills
    assert len(profile.skills) >= 5
    assert "Python" in profile.skills

    # Projects
    assert len(profile.projects) >= 1
