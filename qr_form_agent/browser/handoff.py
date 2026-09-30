"""Continue Here interactive human handoff for login walls and CAPTCHAs.

Enforces Requirement 10:
Opens a visible (headful) browser at the exact state when a login wall or CAPTCHA
is encountered, waits for the user to complete authentication, and resumes automated pre-filling.
"""

import logging
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright

from qr_form_agent.browser.context import create_isolated_context
from qr_form_agent.browser.dom_extractor import extract_form_dom
from qr_form_agent.core.db import Database, JobRecord
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.triage.classifier import classify_page
from qr_form_agent.triage.models import TriageStatus

logger = logging.getLogger(__name__)


def execute_continue_here_handoff(
    job_id: str,
    db: Database,
    interactive_prompt: bool = True,
) -> Tuple[bool, JobRecord, str]:
    """
    Executes a headful handoff for a job currently stuck at LOGIN_WALL, CAPTCHA, or NEEDS_HUMAN.
    Allows the human operator to log in or solve challenges, then captures post-auth DOM
    and resumes automated processing.
    """
    job = db.get_job(job_id)
    if not job:
        raise KeyError(f"Job {job_id} not found")

    logger.info("[HANDOFF_START] Initiating headful handoff for Job %s at %s", job_id, job.url)

    with sync_playwright() as p:
        browser, context = create_isolated_context(p, headless=False, inject_locks=True)
        page = context.new_page()

        try:
            page.goto(job.url, wait_until="domcontentloaded", timeout=30000)

            if interactive_prompt:
                print(f"\n=======================================================")
                print(f"👉 HEADFUL TAKEOVER ACTIVE FOR JOB {job_id}")
                print(f"URL: {job.url}")
                print(f"Please log in or solve CAPTCHA in the open browser window.")
                print(f"When you reach the application form, return here and press Enter.")
                print(f"=======================================================\n")
                input(">>> Press [ENTER] once you have completed login / CAPTCHA <<< ")

            # Capture new post-handoff URL and page state
            current_url = page.url
            triage_res = classify_page(page, current_url)

            # Re-extract fields if form is now accessible
            extraction = extract_form_dom(page)
            extracted_fields = extraction.fields

            # Record handoff resolution in database
            db.log_action(
                job_id,
                "HANDOFF_RESOLVED",
                "HUMAN_OPERATOR",
                {
                    "pre_handoff_url": job.url,
                    "post_handoff_url": current_url,
                    "triage_status": triage_res.status.value,
                    "extracted_fields_count": len(extracted_fields),
                },
            )

            # Transition state from NEEDS_HUMAN back to VISITING if now fillable
            if triage_res.status == TriageStatus.FORM or len(extracted_fields) >= 2:
                updated_job = db.update_job_status(
                    job_id,
                    JobStatus.VISITING,
                    actor="HUMAN_OPERATOR",
                    extra_data={
                        "handoff_completed": True,
                        "current_url": current_url,
                        "form_fields_count": len(extracted_fields),
                    },
                )
                msg = f"Handoff succeeded: Application form unlocked ({len(extracted_fields)} fields ready to fill)."
                return True, updated_job, msg
            else:
                msg = f"Handoff finished, but page status is {triage_res.status.value}."
                return False, job, msg

        finally:
            context.close()
            browser.close()
