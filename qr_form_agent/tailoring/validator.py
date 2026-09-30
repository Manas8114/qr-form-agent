"""No-fabrication validator for AI-drafted cover letters and answers.

Enforces Requirement 5:
Verifies that all factual claims (employers, universities, projects, and skills)
in drafted text exist in the verified profile, flagging any hallucinated or ungrounded assertions.
"""

import logging
import re
from typing import List, Set, Tuple
from pydantic import BaseModel

from qr_form_agent.profile.schema import Profile

logger = logging.getLogger(__name__)


# Common technology and company indicators
COMMON_TECH_LIST = [
    "python", "javascript", "typescript", "c++", "c#", "rust", "golang", "go",
    "java", "kotlin", "swift", "react", "vue", "angular", "node", "django",
    "fastapi", "flask", "pytorch", "tensorflow", "kubernetes", "docker", "aws",
    "gcp", "azure", "sql", "postgresql", "mongodb", "redis", "graphql", "solidity"
]


class ValidationOutcome(BaseModel):
    is_grounded: bool
    unverified_claims: List[str]
    confidence_penalty: float = 0.0


class NoFabricationValidator:
    """
    Validates that claims made in drafted text are strictly grounded in verified Profile data.
    """

    @classmethod
    def get_grounded_entities(cls, profile: Profile) -> Set[str]:
        """Extracts normalized known entities from verified profile."""
        entities: Set[str] = set()

        # 1. Candidate's own name
        if profile.full_name:
            entities.add(profile.full_name.lower().strip())

        # 2. Verified skills
        for skill in profile.skills:
            clean = skill.lower().strip()
            if clean:
                entities.add(clean)

        # 3. Verified companies and roles
        for exp in profile.experience:
            if exp.company:
                entities.add(exp.company.lower().strip())
            if exp.title:
                entities.add(exp.title.lower().strip())

        # 4. Verified education institutions and degrees
        for edu in profile.education:
            if edu.institution:
                entities.add(edu.institution.lower().strip())
            if edu.degree:
                entities.add(edu.degree.lower().strip())
            if edu.field_of_study:
                entities.add(edu.field_of_study.lower().strip())

        # 5. Verified projects and technologies
        for proj in profile.projects:
            if proj.title:
                entities.add(proj.title.lower().strip())
            for tech in proj.technologies:
                entities.add(tech.lower().strip())

        return entities

    @classmethod
    def validate(cls, text: str, profile: Profile) -> ValidationOutcome:
        """
        Scans drafted text for claims and verifies they match profile facts.
        """
        if not text:
            return ValidationOutcome(is_grounded=True, unverified_claims=[])

        grounded = cls.get_grounded_entities(profile)
        unverified: List[str] = []

        # Check for ungrounded employer claims: "at <Company>", "worked for <Company>"
        employer_matches = re.finditer(
            r"(?:worked\s+(?:at|for)|interned\s+at|employed\s+by|experience\s+at)\s+([A-Z][A-Za-z0-9&.-]+(?:\s+[A-Z][A-Za-z0-9&.-]+)?)",
            text,
        )
        for m in employer_matches:
            claimed_comp = m.group(1).strip()
            # Ignore pronouns or generic words
            if claimed_comp.lower() in ("my", "the", "a", "various", "multiple", "several"):
                continue
            if not any(claimed_comp.lower() in g or g in claimed_comp.lower() for g in grounded):
                unverified.append(f"Unverified employer claim: '{claimed_comp}'")

        # Check for ungrounded university / school claims: "graduated from <School>", "degree from <School>"
        edu_matches = re.finditer(
            r"(?:graduated\s+from|degree\s+(?:from|at)|studied\s+at|student\s+at)\s+([A-Z][A-Za-z0-9&.-]+(?:\s+[A-Z][A-Za-z0-9&.-]+)?)",
            text,
        )
        for m in edu_matches:
            claimed_school = m.group(1).strip()
            if claimed_school.lower() in ("my", "the", "a", "university", "college"):
                continue
            if not any(claimed_school.lower() in g or g in claimed_school.lower() for g in grounded):
                unverified.append(f"Unverified university claim: '{claimed_school}'")

        # Check for ungrounded technology claims in prominent tech list
        text_lower = text.lower()
        for tech in COMMON_TECH_LIST:
            # Check if tech is mentioned as a major claim
            pat = rf"\b(?:proficient\s+in|expert\s+in|extensive\s+experience\s+with|built\s+(?:\w+\s+)?with|specialized\s+in)\s+{tech}\b"
            if re.search(pat, text_lower):
                if not any(tech in g for g in grounded):
                    unverified.append(f"Unverified expertise claim: '{tech}'")

        is_grounded = len(unverified) == 0
        penalty = min(0.5, len(unverified) * 0.15)

        if not is_grounded:
            logger.warning("[NO_FABRICATION_FLAG] %d unverified claims found: %s", len(unverified), unverified)

        return ValidationOutcome(
            is_grounded=is_grounded,
            unverified_claims=unverified,
            confidence_penalty=penalty,
        )
