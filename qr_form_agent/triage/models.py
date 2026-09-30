"""Data models and enums for page triage classification.

Enforces Requirement 1:
Classifies each discovered URL into FORM, LANDING_PAGE, LOGIN_WALL, CLOSED, or DEAD.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class TriageStatus(str, Enum):
    FORM = "FORM"                    # Directly fillable application form
    LANDING_PAGE = "LANDING_PAGE"    # Job description / career page with an "Apply" button
    LOGIN_WALL = "LOGIN_WALL"        # Account login required (e.g. Workday account, SSO)
    CLOSED = "CLOSED"                # Application closed / expired / position filled
    DEAD = "DEAD"                    # 404, DNS error, network failure, 500


class TriageResult(BaseModel):
    url: str
    status: TriageStatus
    confidence: float = 1.0
    reason: str
    company: Optional[str] = None
    role: Optional[str] = None
    apply_button_selector: Optional[str] = None
    apply_destination_url: Optional[str] = None
    actionable: bool = False  # True if FORM or LANDING_PAGE that can be processed
