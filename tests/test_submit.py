"""Tests for isolated submission module.

Enforces Hard Requirement 1:
- Submissions are rejected if the job is not in APPROVED state.
- Submissions are aborted if live DOM fields fail to hash-match the approved snapshot.
- Successful submission executes only on approved jobs with verified matching snapshots.
- --dry-run blocks live writes and marks submission simulated.
"""

from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

from qr_form_agent.core.db import Database
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.fill.snapshot import compute_snapshot_hash
from qr_form_agent.submit.submitter import (
    SubmissionSecurityError,
    submit_approved_job,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "forms"


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "submit_test.db"
    return Database(db_path=db_file)


def test_submit_rejects_unapproved_jobs(test_db):
    """Verifies that attempting to submit an unapproved job raises SubmissionSecurityError."""
    job = test_db.create_job("https://example.com/apply")
    assert job.status == JobStatus.QUEUED

    with pytest.raises(SubmissionSecurityError) as exc_info:
        submit_approved_job(job.id, db=test_db)

    assert "Must be APPROVED" in str(exc_info.value)

    # Test in FILLED state
    test_db.update_job_status(job.id, JobStatus.VISITING)
    test_db.update_job_status(job.id, JobStatus.FILLED)

    with pytest.raises(SubmissionSecurityError) as exc_info:
        submit_approved_job(job.id, db=test_db)
    assert "Must be APPROVED" in str(exc_info.value)


def test_submit_aborts_on_hash_mismatch(test_db):
    """Verifies that if live DOM fields differ from approved hash, submission is blocked."""
    job = test_db.create_job("https://example.com/apply")
    test_db.update_job_status(job.id, JobStatus.VISITING)
    test_db.update_job_status(job.id, JobStatus.FILLED)
    test_db.update_job_status(job.id, JobStatus.AWAITING_APPROVAL)

    approved_values = {"first_name": "Alice", "email": "alice@example.com"}
    approved_hash = compute_snapshot_hash(approved_values)

    field_selectors = {
        "first_name": "#first_name",
        "email": "#email",
    }

    # Approve job with Alice's hash
    test_db.update_job_status(
        job.id,
        JobStatus.APPROVED,
        approved_hash=approved_hash,
        extra_data={"approved_values": approved_values, "field_selectors": field_selectors},
    )

    # Now launch browser on 01_standard_job.html but tamper with DOM to have Bob's email
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto((FIXTURES_DIR / "01_standard_job.html").as_uri())

        page.fill("#first_name", "Alice")
        page.fill("#email", "bob_tampered@example.com")  # Tampered!

        # Attempt submit
        with pytest.raises(SubmissionSecurityError) as exc_info:
            submit_approved_job(job.id, db=test_db, page_override=page)

        assert "hash" in str(exc_info.value).lower()

        # Job must have been transitioned to NEEDS_HUMAN due to security hash mismatch
        reloaded = test_db.get_job(job.id)
        assert reloaded.status == JobStatus.NEEDS_HUMAN

        browser.close()


def test_submit_approved_job_dry_run(test_db):
    """Verifies that an approved job in --dry-run mode simulates submit without live action."""
    job = test_db.create_job("https://example.com/apply")
    test_db.update_job_status(job.id, JobStatus.VISITING)
    test_db.update_job_status(job.id, JobStatus.FILLED)
    test_db.update_job_status(job.id, JobStatus.AWAITING_APPROVAL)

    approved_values = {"first_name": "Charlie", "email": "charlie@example.com"}
    approved_hash = compute_snapshot_hash(approved_values)
    field_selectors = {"first_name": "#first_name", "email": "#email"}

    test_db.update_job_status(
        job.id,
        JobStatus.APPROVED,
        approved_hash=approved_hash,
        extra_data={"approved_values": approved_values, "field_selectors": field_selectors},
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto((FIXTURES_DIR / "01_standard_job.html").as_uri())

        page.fill("#first_name", "Charlie")
        page.fill("#email", "charlie@example.com")

        res = submit_approved_job(job.id, db=test_db, dry_run=True, page_override=page)

        assert res.success is True
        assert res.status == JobStatus.SUBMITTED
        assert "DRY-RUN" in res.receipt_text

        # Verify DB updated
        reloaded = test_db.get_job(job.id)
        assert reloaded.status == JobStatus.SUBMITTED

        browser.close()
