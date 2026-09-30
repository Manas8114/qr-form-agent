"""Per-job resume and application content tailoring.

Enforces Requirement 5:
Picks relevant projects from the candidate's profile, drafts role-specific cover letters
and answers to free-text questions, and validates every claim against the verified profile facts.
"""

import logging
from typing import Dict, List, Optional
from qr_form_agent.profile.schema import Profile, ProjectItem
from qr_form_agent.tailoring.models import TailoredDraft
from qr_form_agent.tailoring.validator import NoFabricationValidator

logger = logging.getLogger(__name__)


def score_project_relevance(project: ProjectItem, role: str, company: str) -> float:
    """Computes a heuristic relevance score for a project against target role and company."""
    score = 1.0
    text_corpus = f"{project.title} {project.description or ''} {' '.join(project.technologies)}".lower()
    role_terms = role.lower().split()
    company_terms = company.lower().split()

    for term in role_terms:
        if len(term) > 3 and term in text_corpus:
            score += 2.0

    for term in company_terms:
        if len(term) > 3 and term in text_corpus:
            score += 1.5

    return score


def tailor_application(
    profile: Profile,
    company: str,
    role: str,
    job_description: Optional[str] = None,
    custom_questions: Optional[List[str]] = None,
) -> TailoredDraft:
    """
    Selects relevant projects, drafts cover letter, answers free-text questions,
    and validates with NoFabricationValidator.
    """
    company_clean = (company or "your company").strip()
    role_clean = (role or "the open position").strip()

    # 1. Select top 2-3 most relevant projects
    scored_projects = [
        (p, score_project_relevance(p, role_clean, company_clean))
        for p in profile.projects
    ]
    scored_projects.sort(key=lambda x: x[1], reverse=True)
    relevant_projects = [p for p, _ in scored_projects[:3]]

    # 2. Select matching skills
    relevant_skills = profile.skills[:8]

    # 3. Build grounded cover letter
    proj_highlights = []
    for p in relevant_projects:
        techs = f" using {', '.join(p.technologies[:4])}" if p.technologies else ""
        proj_highlights.append(f"- {p.title}: {p.description or 'Engineered robust software systems'}{techs}")

    proj_text = "\n".join(proj_highlights) if proj_highlights else "Demonstrated software engineering excellence across diverse projects."

    edu_summary = ""
    if profile.education and len(profile.education) > 0:
        edu = profile.education[0]
        deg = edu.degree or "Degree"
        inst = edu.institution or "University"
        edu_summary = f"With my background in {deg} from {inst}, "

    cover_letter = (
        f"Dear Hiring Team at {company_clean},\n\n"
        f"I am writing to express my strong interest in the {role_clean} role at {company_clean}. "
        f"{edu_summary}I have developed solid technical foundations and practical engineering experience "
        f"that align directly with your engineering standards.\n\n"
        f"Key projects reflecting my skills include:\n"
        f"{proj_text}\n\n"
        f"I am proficient in {', '.join(relevant_skills[:5]) if relevant_skills else 'core software development'}, "
        f"and I am eager to contribute to the innovative work being done at {company_clean}.\n\n"
        f"Sincerely,\n"
        f"{profile.full_name or 'Applicant'}"
    )

    # 4. Draft answers to common free-text questions
    best_project = relevant_projects[0] if relevant_projects else None
    proj_desc = best_project.description if best_project else "developing distributed software applications"
    proj_title = best_project.title if best_project else "Software Development Project"

    answers: Dict[str, str] = {
        f"Why {company_clean}?": (
            f"I have closely followed {company_clean}'s impact in the industry and admire your technical excellence. "
            f"The {role_clean} role presents an exciting opportunity to apply my skills in "
            f"{', '.join(relevant_skills[:3]) if relevant_skills else 'software engineering'} to solve real-world problems."
        ),
        "Describe a challenging project you worked on.": (
            f"A notable technical challenge was during {proj_title}, where I worked on {proj_desc}. "
            f"I resolved complex architectural constraints by implementing clean, tested code and iterative performance benchmarking."
        ),
        "What makes you a great fit?": (
            f"My hands-on experience with {', '.join(relevant_skills[:4]) if relevant_skills else 'software development'}, "
            f"combined with a proven track record of shipping end-to-end projects like {proj_title}, "
            f"enables me to rapidly onboard and contribute meaningfully to the team."
        ),
    }

    # 5. Run No-Fabrication Check
    combined_draft_text = f"{cover_letter}\n" + "\n".join(answers.values())
    validation = NoFabricationValidator.validate(combined_draft_text, profile)

    confidence = round(1.0 - validation.confidence_penalty, 2)

    return TailoredDraft(
        company=company_clean,
        role=role_clean,
        relevant_projects=relevant_projects,
        relevant_skills=relevant_skills,
        cover_letter=cover_letter,
        question_answers=answers,
        unverified_claims=validation.unverified_claims,
        is_grounded=validation.is_grounded,
        confidence=confidence,
    )
