"""Tests for Per-Job Application Tailoring & No-Fabrication Check.

Enforces Requirement 5:
- Tailors cover letters and project selection for target roles.
- Flags any claims (employers, degrees, technologies) not grounded in verified profile.
"""

import pytest

from qr_form_agent.profile.schema import EducationItem, ExperienceItem, Profile, ProjectItem
from qr_form_agent.tailoring.models import TailoredDraft
from qr_form_agent.tailoring.synthesizer import score_project_relevance, tailor_application
from qr_form_agent.tailoring.validator import NoFabricationValidator


@pytest.fixture
def candidate_profile():
    return Profile(
        full_name="Alex Morgan",
        email="alex.morgan@example.com",
        skills=["Python", "FastAPI", "TypeScript", "PostgreSQL", "Docker"],
        education=[
            EducationItem(
                institution="UC Berkeley",
                degree="B.S. Computer Science",
                end_year="2024",
            )
        ],
        experience=[
            ExperienceItem(
                company="Tech Solutions Inc",
                title="Software Engineer Intern",
                description="Built automated data pipelines",
            )
        ],
        projects=[
            ProjectItem(
                name="QR Form Agent",
                description="Autonomous form pre-filler using Playwright and LLM mapping",
                technologies=["Python", "FastAPI", "Playwright"],
            ),
            ProjectItem(
                name="Mobile Weather App",
                description="React Native weather tracking application",
                technologies=["React Native", "TypeScript"],
            ),
        ],
    )


def test_project_relevance_scoring():
    """Projects matching role keywords receive higher relevance scores."""
    p_backend = ProjectItem(
        name="High-throughput API",
        description="Scalable backend with Python and Redis",
        technologies=["Python", "Redis", "FastAPI"],
    )
    p_frontend = ProjectItem(
        name="Design System UI",
        description="CSS component library for web design",
        technologies=["CSS", "HTML", "Figma"],
    )

    score_be = score_project_relevance(p_backend, role="Python Backend Engineer", company="Stripe")
    score_fe = score_project_relevance(p_frontend, role="Python Backend Engineer", company="Stripe")

    assert score_be > score_fe


def test_tailor_application_generates_grounded_draft(candidate_profile):
    """Tailoring generates cover letter and question answers with high confidence."""
    draft: TailoredDraft = tailor_application(
        profile=candidate_profile,
        company="Datadog",
        role="Backend Software Engineer",
    )

    assert draft.company == "Datadog"
    assert draft.role == "Backend Software Engineer"
    assert len(draft.relevant_projects) >= 1
    assert "Datadog" in draft.cover_letter
    assert "Alex Morgan" in draft.cover_letter
    assert draft.is_grounded is True
    assert len(draft.unverified_claims) == 0
    assert draft.confidence >= 0.90


def test_no_fabrication_validator_passes_verified_profile(candidate_profile):
    """Text containing only verified profile facts passes without flags."""
    text = (
        "I graduated from UC Berkeley with a B.S. Computer Science. "
        "During my time at Tech Solutions Inc, I built automated data pipelines. "
        "I am proficient in Python and FastAPI, and built the QR Form Agent project."
    )

    outcome = NoFabricationValidator.validate(text, candidate_profile)
    assert outcome.is_grounded is True
    assert len(outcome.unverified_claims) == 0
    assert outcome.confidence_penalty == 0.0


def test_no_fabrication_validator_flags_unverified_employer(candidate_profile):
    """Detects and flags employer claims not present in profile."""
    text = (
        "I have extensive software experience having worked at Goldman Sachs "
        "and previously interned at Google on distributed database systems."
    )

    outcome = NoFabricationValidator.validate(text, candidate_profile)
    assert outcome.is_grounded is False
    assert any("Goldman Sachs" in claim for claim in outcome.unverified_claims)
    assert any("Google" in claim for claim in outcome.unverified_claims)
    assert outcome.confidence_penalty > 0.0


def test_no_fabrication_validator_flags_unverified_university(candidate_profile):
    """Detects and flags university/degree claims not in profile."""
    text = "I received my Masters degree from Stanford University in 2025."

    outcome = NoFabricationValidator.validate(text, candidate_profile)
    assert outcome.is_grounded is False
    assert any("Stanford University" in claim for claim in outcome.unverified_claims)


def test_no_fabrication_validator_flags_unverified_technologies(candidate_profile):
    """Detects and flags expertise claims in technologies not listed in profile."""
    text = "I am an expert in Solidity and specialized in Kubernetes cluster administration."

    outcome = NoFabricationValidator.validate(text, candidate_profile)
    assert outcome.is_grounded is False
    assert any("solidity" in claim.lower() for claim in outcome.unverified_claims)
    assert any("kubernetes" in claim.lower() for claim in outcome.unverified_claims)
