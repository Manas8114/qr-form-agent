"""Submission package with mandatory approved state and snapshot verification."""

from qr_form_agent.submit.confirmation import capture_submission_confirmation
from qr_form_agent.submit.submitter import (
    SubmissionSecurityError,
    SubmitResult,
    submit_approved_job,
)
from qr_form_agent.submit.verifier import verify_dom_matches_approved_snapshot

__all__ = [
    "SubmissionSecurityError",
    "SubmitResult",
    "submit_approved_job",
    "verify_dom_matches_approved_snapshot",
    "capture_submission_confirmation",
]
