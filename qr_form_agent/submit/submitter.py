"""Isolated submission module.

Enforces Hard Requirement 1:
- Submit lives in a separate module that accepts ONLY an approved job_id.
- Re-checks that current field values hash-match the approved snapshot, and aborts on mismatch.
- After submit, captures confirmation screenshot and receipt text.
- Supports --dry-run mode (network writes/submits simulated).
"""

import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from playwright.sync_api import Browser, Page, sync_playwright

from qr_form_agent.config import settings
from qr_form_agent.core.db import Database, JobRecord
from qr_form_agent.core.kill_switch import enforce_kill_switch
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.submit.confirmation import capture_submission_confirmation
from qr_form_agent.submit.verifier import verify_dom_matches_approved_snapshot

logger = logging.getLogger(__name__)


class SubmitResult(BaseModel):
    success: bool
    job_id: str
    status: JobStatus
    receipt_text: Optional[str] = None
    confirmation_screenshot: Optional[str] = None
    error_message: Optional[str] = None


class SubmissionSecurityError(RuntimeError):
    """Raised when submission safety invariants are violated."""
    pass


def submit_approved_job(
    job_id: str,
    db: Optional[Database] = None,
    dry_run: Optional[bool] = None,
    page_override: Optional[Page] = None,
) -> SubmitResult:
    """
    Submits a form for a given job_id.
    Strictly accepts ONLY an approved job. Re-verifies that live field values
    hash-match the approved snapshot, and terminates immediately on any mismatch.
    """
    enforce_kill_switch()

    database = db or Database()
    job = database.get_job(job_id)
    if not job:
        raise KeyError(f"Job not found: {job_id}")

    # Security Invariant 1: Job MUST be in APPROVED state
    if job.status != JobStatus.APPROVED:
        database.log_action(
            job_id,
            "UNAUTHORIZED_SUBMIT_ATTEMPT",
            "SYSTEM",
            {"attempted_status": job.status.value},
        )
        raise SubmissionSecurityError(
            f"Security Violation: Cannot submit job {job_id} in status '{job.status.value}'. Must be APPROVED."
        )

    # Security Invariant 2: Job MUST possess an approved snapshot hash
    approved_hash = job.approved_snapshot_hash
    if not approved_hash:
        raise SubmissionSecurityError(f"Security Violation: Job {job_id} lacks approved_snapshot_hash.")

    is_dry_run = dry_run if dry_run is not None else settings.dry_run

    # If page_override is provided (e.g. from tests or active session)
    if page_override:
        return _execute_submission_on_page(page_override, job, database, approved_hash, is_dry_run)

    # Otherwise open fresh browser session
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(job.url)
        try:
            return _execute_submission_on_page(
                page, job, database, approved_hash, is_dry_run, populate_before_verify=True
            )
        finally:
            context.close()
            browser.close()


def _execute_submission_on_page(
    page: Page,
    job: JobRecord,
    db: Database,
    approved_hash: str,
    dry_run: bool,
    populate_before_verify: bool = False,
) -> SubmitResult:
    stage_data = job.stage_data
    approved_values = stage_data.get("approved_values", {})
    field_selectors = stage_data.get("field_selectors", {})

    # 1. If explicitly requested (e.g. freshly opened page without state), populate fields
    if populate_before_verify:
        for field_id, val in approved_values.items():
            sel = field_selectors.get(field_id)
            if sel and val is not None:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        tag = loc.evaluate("el => el.tagName.toLowerCase()")
                        el_type = loc.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
                        if el_type == "checkbox":
                            loc.set_checked(bool(val))
                        elif el_type == "radio":
                            loc.check()
                        elif tag == "select":
                            loc.select_option(value=str(val))
                        else:
                            loc.fill(str(val))
                except Exception as e:
                    logger.warning("Error populating field %s: %s", field_id, e)

    # 2. Cryptographic snapshot hash verification on CURRENT live field values
    is_match, live_hash, _ = verify_dom_matches_approved_snapshot(
        page, field_selectors, approved_hash
    )

    if not is_match:
        # Abort immediately on mismatch! Transition to NEEDS_HUMAN
        db.update_job_status(
            job.id,
            JobStatus.NEEDS_HUMAN,
            actor="SYSTEM",
            extra_data={"hash_mismatch": {"expected": approved_hash, "actual": live_hash}},
        )
        db.log_action(
            job.id,
            "SUBMIT_ABORTED_HASH_MISMATCH",
            "SYSTEM",
            {"expected_hash": approved_hash, "actual_hash": live_hash},
        )
        raise SubmissionSecurityError(
            f"Security Violation: Current DOM hash ({live_hash}) does not match approved snapshot ({approved_hash}). Aborted!"
        )

    # 3. Dry-run enforcement
    if dry_run:
        logger.info("[DRY_RUN] Submission simulated for approved job %s", job.id)
        db.update_job_status(
            job.id,
            JobStatus.SUBMITTED,
            actor="HUMAN_OPERATOR",
            extra_data={"dry_run": True},
        )
        return SubmitResult(
            success=True,
            job_id=job.id,
            status=JobStatus.SUBMITTED,
            receipt_text="[DRY-RUN SIMULATED SUCCESS: Network writes blocked]",
            confirmation_screenshot=None,
        )

    # 4. Live submission execution
    submit_btn = page.locator('button[type="submit"], input[type="submit"]').first
    if submit_btn.count() == 0:
        submit_btn = page.locator('button:has-text("Submit"), button:has-text("Apply")').first

    if submit_btn.count() == 0:
        raise RuntimeError("No submit button could be located on page.")

    submit_btn.click()
    page.wait_for_timeout(1000)

    # 5. Capture confirmation
    receipt, conf_screenshot = capture_submission_confirmation(page, job.id)

    db.update_job_status(
        job.id,
        JobStatus.SUBMITTED,
        actor="HUMAN_OPERATOR",
        extra_data={"receipt": receipt},
        confirmation_screenshot_path=conf_screenshot,
    )

    return SubmitResult(
        success=True,
        job_id=job.id,
        status=JobStatus.SUBMITTED,
        receipt_text=receipt,
        confirmation_screenshot=conf_screenshot,
    )
