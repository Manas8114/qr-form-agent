"""Triage module for classifying career URLs before filling."""

from qr_form_agent.triage.models import TriageResult, TriageStatus
from qr_form_agent.triage.classifier import classify_page
from qr_form_agent.triage.landing_hopper import follow_apply_button
from qr_form_agent.triage.report import generate_triage_table, summarize_triage

__all__ = [
    "TriageStatus",
    "TriageResult",
    "classify_page",
    "follow_apply_button",
    "generate_triage_table",
    "summarize_triage",
]
