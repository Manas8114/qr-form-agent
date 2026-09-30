"""Tailoring module for role-specific cover letters and answers with no-fabrication validation."""

from qr_form_agent.tailoring.models import TailoredDraft
from qr_form_agent.tailoring.synthesizer import tailor_application
from qr_form_agent.tailoring.validator import NoFabricationValidator, ValidationOutcome

__all__ = [
    "TailoredDraft",
    "tailor_application",
    "NoFabricationValidator",
    "ValidationOutcome",
]
