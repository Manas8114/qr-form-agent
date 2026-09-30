"""Tests for core state machine transitions, SQLite persistence, and kill switch."""

from pathlib import Path
import pytest

from qr_form_agent.core.db import Database
from qr_form_agent.core.kill_switch import (
    activate_kill_switch,
    deactivate_kill_switch,
    enforce_kill_switch,
    is_kill_switch_active,
    KillSwitchTriggeredError,
)
from qr_form_agent.core.state_machine import (
    InvalidStateTransitionError,
    JobStatus,
    validate_transition,
)


def test_valid_state_transitions():
    # Normal happy path
    validate_transition(JobStatus.QUEUED, JobStatus.VISITING)
    validate_transition(JobStatus.VISITING, JobStatus.FILLED)
    validate_transition(JobStatus.FILLED, JobStatus.AWAITING_APPROVAL)
    validate_transition(JobStatus.AWAITING_APPROVAL, JobStatus.APPROVED)
    validate_transition(JobStatus.APPROVED, JobStatus.SUBMITTED)

    # Rejection path
    validate_transition(JobStatus.AWAITING_APPROVAL, JobStatus.REJECTED)

    # Needs human intervention
    validate_transition(JobStatus.VISITING, JobStatus.NEEDS_HUMAN)
    validate_transition(JobStatus.NEEDS_HUMAN, JobStatus.VISITING)


def test_submission_without_approval_is_impossible():
    """Enforces Requirement 1: Transitioning to SUBMITTED directly from FILLED or QUEUED is illegal!"""
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(JobStatus.FILLED, JobStatus.SUBMITTED)

    with pytest.raises(InvalidStateTransitionError):
        validate_transition(JobStatus.AWAITING_APPROVAL, JobStatus.SUBMITTED)

    with pytest.raises(InvalidStateTransitionError):
        validate_transition(JobStatus.QUEUED, JobStatus.SUBMITTED)


def test_db_job_lifecycle_and_audit(tmp_path: Path):
    db_file = tmp_path / "test_lifecycle.db"
    db = Database(db_path=db_file)

    job = db.create_job("https://example.com/apply")
    assert job.status == JobStatus.QUEUED

    # Update to VISITING
    job = db.update_job_status(job.id, JobStatus.VISITING)
    assert job.status == JobStatus.VISITING

    # Update to FILLED
    job = db.update_job_status(job.id, JobStatus.FILLED, extra_data={"fields_count": 5})
    assert job.status == JobStatus.FILLED

    # Update to AWAITING_APPROVAL
    job = db.update_job_status(job.id, JobStatus.AWAITING_APPROVAL, approved_hash="abc123hash")
    assert job.status == JobStatus.AWAITING_APPROVAL
    assert job.approved_snapshot_hash == "abc123hash"

    # Verify audit logs
    logs = db.get_audit_logs(job.id)
    assert len(logs) >= 4
    actions = [l.action for l in logs]
    assert "JOB_CREATED" in actions
    assert "STATUS_CHANGE" in actions


def test_kill_switch():
    deactivate_kill_switch()
    assert is_kill_switch_active() is False

    activate_kill_switch("Test alert")
    assert is_kill_switch_active() is True

    with pytest.raises(KillSwitchTriggeredError):
        enforce_kill_switch()

    deactivate_kill_switch()
    assert is_kill_switch_active() is False
