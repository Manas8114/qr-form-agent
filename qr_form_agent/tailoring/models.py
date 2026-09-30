"""Data models for per-job resume and application tailoring."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from qr_form_agent.profile.schema import ProjectItem


class TailoredDraft(BaseModel):
    company: str
    role: str
    relevant_projects: List[ProjectItem] = Field(default_factory=list)
    relevant_skills: List[str] = Field(default_factory=list)
    cover_letter: str = ""
    question_answers: Dict[str, str] = Field(default_factory=dict)
    unverified_claims: List[str] = Field(default_factory=list)
    is_grounded: bool = True
    confidence: float = 1.0
