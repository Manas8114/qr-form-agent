"""Job state machine and valid transition rules.

States:
QUEUED -> VISITING -> FILLED -> AWAITING_APPROVAL -> APPROVED -> SUBMITTED
                                                  -> REJECTED
Any active state -> NEEDS_HUMAN (e.g. CAPTCHA, Denylist, MFA)
Any state -> FAILED (on fatal unrecoverable errors)
"""

from enum import Enum
from typing import Dict, Set


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    VISITING = "VISITING"
    FILLED = "FILLED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    FAILED = "FAILED"


# Strict allowable state transitions
VALID_TRANSITIONS: Dict[JobStatus, Set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.VISITING, JobStatus.NEEDS_HUMAN, JobStatus.REJECTED, JobStatus.FAILED},
    JobStatus.VISITING: {JobStatus.FILLED, JobStatus.NEEDS_HUMAN, JobStatus.FAILED},
    JobStatus.FILLED: {JobStatus.AWAITING_APPROVAL, JobStatus.NEEDS_HUMAN, JobStatus.FAILED},
    JobStatus.AWAITING_APPROVAL: {JobStatus.APPROVED, JobStatus.REJECTED, JobStatus.NEEDS_HUMAN, JobStatus.FAILED},
    # CRITICAL: SUBMITTED can ONLY be reached from APPROVED!
    JobStatus.APPROVED: {JobStatus.SUBMITTED, JobStatus.NEEDS_HUMAN, JobStatus.FAILED},
    JobStatus.NEEDS_HUMAN: {JobStatus.VISITING, JobStatus.FILLED, JobStatus.AWAITING_APPROVAL, JobStatus.REJECTED, JobStatus.FAILED},
    JobStatus.SUBMITTED: set(),  # Terminal state
    JobStatus.REJECTED: set(),   # Terminal state
    JobStatus.FAILED: set(),     # Terminal state
}


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal state machine transition is attempted."""
    pass


def validate_transition(current_status: JobStatus, new_status: JobStatus) -> None:
    """
    Validates whether transition from current_status to new_status is permitted.
    Raises InvalidStateTransitionError if illegal.
    """
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal state transition: Cannot transition job from {current_status.value} to {new_status.value}."
        )
