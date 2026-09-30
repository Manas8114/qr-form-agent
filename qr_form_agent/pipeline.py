"""End-to-end human-in-the-loop form automation pipeline."""

import logging
from pathlib import Path
from typing import List, Optional
from playwright.sync_api import sync_playwright

from qr_form_agent.browser.context import create_isolated_context
from qr_form_agent.browser.dom_extractor import extract_form_dom
from qr_form_agent.browser.stepper import launch_headful_takeover
from qr_form_agent.config import settings
from qr_form_agent.core.db import Database, JobRecord
from qr_form_agent.core.kill_switch import enforce_kill_switch
from qr_form_agent.core.rate_limiter import DomainRateLimiter
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.fill.filler import FillItem, fill_form_fields
from qr_form_agent.fill.route_guard import FillRouteGuard
from qr_form_agent.fill.snapshot import capture_form_snapshot
from qr_form_agent.mapping.engine import MappingEngine, MappingPipelineResult
from qr_form_agent.profile.extractor import extract_text_from_pdf
from qr_form_agent.profile.schema import Profile
from qr_form_agent.profile.storage import load_verified_profile, save_verified_profile
from qr_form_agent.profile.synthesizer import synthesize_profile
from qr_form_agent.qr.decoder import decode_qr_codes
from qr_form_agent.review.notifications import notify_job_awaiting_approval
from qr_form_agent.safety.gate import run_safety_gate
from qr_form_agent.submit.submitter import submit_approved_job

logger = logging.getLogger(__name__)


class FormAgentPipeline:
    def __init__(self, db: Optional[Database] = None, dry_run: bool = False):
        self.db = db or Database()
        self.dry_run = dry_run or settings.dry_run
        self.rate_limiter = DomainRateLimiter()
        self.mapping_engine = MappingEngine()

    def get_or_create_profile(self, resume_path: Optional[Path] = None) -> Profile:
        """Loads cached verified profile.json or parses once from PDF resume."""
        profile = load_verified_profile()
        if profile:
            logger.info("Loaded existing verified profile (%s)", profile.email)
            return profile

        if not resume_path or not resume_path.exists():
            raise FileNotFoundError(
                "No verified profile.json found, and no valid resume PDF path was provided."
            )

        logger.info("Parsing resume PDF for the first time: %s", resume_path)
        text = extract_text_from_pdf(resume_path)
        profile = synthesize_profile(text)
        profile.resume_file_path = str(resume_path.resolve())

        save_verified_profile(profile)
        logger.info("Saved initial verified profile to disk.")
        return profile

    def process_qr_image(
        self,
        image_path: Path,
        resume_pdf_path: Optional[Path] = None,
        auto_confirm_urls: bool = False,
    ) -> List[str]:
        """
        Executes stages 1 through 4:
        1. Decode all QR codes
        2. Filter via Safety Gate
        3. Extract forms & map fields under sandbox lock
        4. Populate & capture snapshot -> transitions to AWAITING_APPROVAL
        """
        enforce_kill_switch()
        profile = self.get_or_create_profile(resume_pdf_path)

        # Stage 1: Decode QR codes
        scan_result = decode_qr_codes(image_path)
        print(f"\n[QR SCAN] Found {scan_result.total_found} barcodes ({scan_result.unique_count} unique).")

        if not scan_result.urls:
            print("[QR SCAN] No QR codes detected.")
            return []

        # Stage 2: URL Safety Gate
        gate_report = run_safety_gate(
            scan_result.urls,
            auto_confirm=auto_confirm_urls,
        )

        if not gate_report.approved_urls:
            print("[SAFETY GATE] No URLs approved by operator or safety checks.")
            return []

        created_job_ids = []

        # Stage 3: Process each approved URL in isolated sandbox
        with sync_playwright() as p:
            for url in gate_report.approved_urls:
                enforce_kill_switch()
                self.rate_limiter.wait_for_domain(url)

                job = self.db.create_job(url)
                created_job_ids.append(job.id)
                print(f"\n[JOB {job.id[:8]}] Visiting {url}...")

                browser, context = create_isolated_context(p, headless=True, inject_locks=True)
                page = context.new_page()

                route_guard = FillRouteGuard(page)
                route_guard.install()

                try:
                    self.db.update_job_status(job.id, JobStatus.VISITING)
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)

                    # Extract DOM
                    extraction = extract_form_dom(page)

                    # Denylist & CAPTCHA checks
                    if extraction.has_captcha or extraction.has_login_or_password:
                        print(f"[JOB {job.id[:8]}] CAPTCHA or Login required -> Transitioning to NEEDS_HUMAN")
                        self.db.update_job_status(
                            job.id,
                            JobStatus.NEEDS_HUMAN,
                            extra_data={"reason": "CAPTCHA / Login detected"},
                        )
                        continue

                    # Mapping
                    mapping_res: MappingPipelineResult = self.mapping_engine.process_form_fields(
                        url, extraction.fields, profile
                    )

                    if mapping_res.has_denylisted_fields:
                        print(f"[JOB {job.id[:8]}] Sensitive fields detected -> Transitioning to NEEDS_HUMAN")
                        self.db.update_job_status(
                            job.id,
                            JobStatus.NEEDS_HUMAN,
                            extra_data={"denylist_reasons": mapping_res.denylist_reasons},
                        )
                        continue

                    # Populate form fields safely
                    fill_items = [
                        FillItem(
                            field_id=m.field_id,
                            selector=m.selector,
                            value=m.value,
                            is_resume_upload=m.is_resume_upload,
                            flagged_for_review=m.flagged_for_review,
                        )
                        for m in mapping_res.mapped_fields
                    ]
                    fill_summary = fill_form_fields(page, fill_items, resume_path=profile.resume_file_path)

                    # Capture snapshot & screenshot
                    field_selectors = {m.field_id: m.selector for m in mapping_res.mapped_fields}
                    live_vals, snap_hash, screenshot_path = capture_form_snapshot(page, job.id, field_selectors)

                    stage_data = {
                        "mapped_fields": [m.model_dump() for m in mapping_res.mapped_fields],
                        "field_selectors": field_selectors,
                        "fill_summary": fill_summary.model_dump(),
                    }

                    # Transition to AWAITING_APPROVAL
                    target_status = JobStatus.NEEDS_HUMAN if mapping_res.needs_human else JobStatus.AWAITING_APPROVAL
                    self.db.update_job_status(
                        job.id,
                        target_status,
                        extra_data=stage_data,
                        approved_hash=snap_hash,
                        screenshot_path=screenshot_path,
                    )

                    # Trigger optional Telegram notification
                    review_link = f"http://{settings.review_server_host}:{settings.review_server_port}"
                    notify_job_awaiting_approval(job.id, url, review_link)

                    print(f"[JOB {job.id[:8]}] Form pre-filled & locked. Status: {target_status.value}")
                    print(f"             Snapshot Hash: {snap_hash[:16]}...")
                    print(f"             Review at: {review_link}")

                except Exception as e:
                    logger.error("Error processing job %s: %s", job.id, e)
                    self.db.update_job_status(
                        job.id,
                        JobStatus.FAILED,
                        extra_data={"error": str(e)},
                    )
                finally:
                    route_guard.uninstall()
                    page.close()
                    context.close()
                    browser.close()

        return created_job_ids
