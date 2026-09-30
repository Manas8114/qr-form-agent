"""End-to-end human-in-the-loop form automation pipeline.

Enforces Requirements 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15:
- Label OCR & QR decoding
- Batch re-scan URL diffing
- SSRF URL safety gate
- Pre-fill triage (FORM, LANDING_PAGE, LOGIN_WALL, CLOSED, DEAD)
- 1-hop Apply navigation for landing pages
- Workday, Greenhouse, Lever, CoreHR adapters
- Saved Answers Bank integration
- Per-job tailoring with no-fabrication validation
- Sandbox fill quarantine (zero submit primitives, pinned DNS route guard)
- Dry-run audit report
- Cryptographic SHA-256 snapshot generation & human review staging
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from PIL import Image
from playwright.sync_api import sync_playwright
from rich.console import Console

from qr_form_agent.adapters.registry import AdapterRegistry
from qr_form_agent.browser.context import create_isolated_context
from qr_form_agent.browser.dom_extractor import extract_form_dom
from qr_form_agent.config import settings
from qr_form_agent.core.db import Database, JobRecord
from qr_form_agent.core.kill_switch import enforce_kill_switch
from qr_form_agent.core.rate_limiter import DomainRateLimiter
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.fill.dry_run_report import DryRunReport, build_dry_run_report
from qr_form_agent.fill.filler import FillItem, fill_form_fields
from qr_form_agent.fill.route_guard import FillRouteGuard
from qr_form_agent.fill.snapshot import capture_form_snapshot
from qr_form_agent.mapping.engine import MappingEngine, MappingPipelineResult
from qr_form_agent.profile.answers_bank import AnswersBank
from qr_form_agent.profile.extractor import extract_text_from_pdf
from qr_form_agent.profile.schema import Profile
from qr_form_agent.profile.storage import load_verified_profile, save_verified_profile
from qr_form_agent.profile.synthesizer import synthesize_profile
from qr_form_agent.qr.decoder import decode_qr_codes
from qr_form_agent.qr.label_ocr import QRLabelMetadata, extract_qr_labels
from qr_form_agent.review.notifications import notify_job_awaiting_approval
from qr_form_agent.safety.dedupe import diff_against_existing_urls
from qr_form_agent.safety.gate import run_safety_gate
from qr_form_agent.tailoring.synthesizer import tailor_application
from qr_form_agent.tracker.tracker import ApplicationTracker
from qr_form_agent.triage.classifier import classify_page
from qr_form_agent.triage.landing_hopper import follow_apply_button
from qr_form_agent.triage.models import TriageResult, TriageStatus
from qr_form_agent.triage.report import generate_triage_table, summarize_triage

logger = logging.getLogger(__name__)
console = Console()


class FormAgentPipeline:
    def __init__(
        self,
        db: Optional[Database] = None,
        dry_run: bool = False,
        answers_bank: Optional[AnswersBank] = None,
    ):
        self.db = db or Database()
        self.dry_run = dry_run or settings.dry_run
        self.rate_limiter = DomainRateLimiter()
        self.answers_bank = answers_bank or AnswersBank()
        self.mapping_engine = MappingEngine(answers_bank=self.answers_bank)
        self.tracker = ApplicationTracker(self.db)

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

        logger.info("Parsing resume PDF: %s", resume_path)
        text = extract_text_from_pdf(resume_path)
        profile = synthesize_profile(text)
        profile.resume_file_path = str(resume_path.resolve())

        save_verified_profile(profile)
        logger.info("Saved verified candidate profile to disk.")
        return profile

    def process_qr_image(
        self,
        image_path: Path,
        resume_pdf_path: Optional[Path] = None,
        auto_confirm_urls: bool = False,
        include_seen: bool = False,
    ) -> List[str]:
        """
        Executes the full pipeline:
        1. Decode all QR codes & spatial label OCR (company, role, deadline, notices)
        2. Batch re-scan diff against already-seen URLs
        3. SSRF URL safety gate
        4. Triage classification (FORM, LANDING_PAGE, LOGIN_WALL, CLOSED, DEAD)
        5. Landing page 1-hop Apply navigation
        6. Specialized ATS adapters / mapping + per-job tailoring
        7. Pre-fill & SHA-256 snapshot capture (or dry-run report)
        """
        enforce_kill_switch()
        profile = self.get_or_create_profile(resume_pdf_path)

        # Stage 1: Decode QR codes and perform spatial label OCR
        scan_result = decode_qr_codes(image_path)
        print(f"\n[QR SCAN] Found {scan_result.total_found} barcodes ({scan_result.unique_count} unique).")

        if not scan_result.urls:
            print("[QR SCAN] No QR codes detected in image.")
            return []

        # Read printed labels near each QR code
        labels_map: Dict[str, QRLabelMetadata] = {}
        try:
            with Image.open(image_path) as pil_img:
                raw_labels = extract_qr_labels(pil_img, scan_result.barcodes)
                for lbl in raw_labels:
                    labels_map[lbl.url] = lbl
        except Exception as e:
            logger.debug("Label OCR step failed or skipped: %s", e)

        # Stage 2: Batch re-scan diff against existing tracked applications
        all_tracked = self.db.list_jobs()
        tracked_urls = {j.url for j in all_tracked}
        new_urls, seen_urls = diff_against_existing_urls(scan_result.urls, tracked_urls)

        if seen_urls and not include_seen:
            print(f"[BATCH RE-SCAN] {len(seen_urls)} of {len(scan_result.urls)} URLs were already tracked. Focusing on {len(new_urls)} new.")
            urls_to_process = new_urls
        else:
            urls_to_process = scan_result.urls

        if not urls_to_process:
            print("[BATCH RE-SCAN] All discovered QR codes have already been processed! Use --include-seen to re-run.")
            return []

        # Stage 3: URL Safety Gate
        gate_report = run_safety_gate(urls_to_process, auto_confirm=auto_confirm_urls)
        if not gate_report.approved_urls:
            print("[SAFETY GATE] No URLs approved by operator or safety criteria.")
            return []

        created_job_ids: List[str] = []
        triage_results: List[TriageResult] = []

        # Stage 4 & 5: Visit in isolated sandbox, Triage, Follow Landing Pages, and Pre-Fill
        with sync_playwright() as p:
            for url in gate_report.approved_urls:
                enforce_kill_switch()
                self.rate_limiter.wait_for_domain(url)

                # Retrieve label OCR metadata if present
                lbl = labels_map.get(url)
                company = lbl.company if lbl else None
                role = lbl.role if lbl else None
                deadline = lbl.deadline if lbl else None
                opening_date = lbl.opening_date if lbl else None
                notes = lbl.notes if lbl else None

                # Check duplicate application (company + role)
                is_dup, dup_reason = self.tracker.check_duplicate(url, company, role)
                if is_dup:
                    print(f"\n[DUPLICATE DETECTED] Skipping {url}: {dup_reason}")
                    continue

                # Create Job Record
                job = self.db.create_job(
                    url,
                    company=company,
                    role=role,
                    deadline=deadline,
                    opening_date=opening_date,
                    notes=notes,
                )
                created_job_ids.append(job.id)
                print(f"\n[JOB {job.id[:8]}] Inspecting {company or 'Job'} ({role or url})...")

                browser, context = create_isolated_context(p, headless=True, inject_locks=True)
                page = context.new_page()

                route_guard = FillRouteGuard(page)
                route_guard.install()

                try:
                    self.db.update_job_status(job.id, JobStatus.VISITING)
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1000)

                    # 1. Triage Classification
                    t_res = classify_page(page, url)
                    t_res.company = company
                    t_res.role = role
                    triage_results.append(t_res)

                    # Update triage info in DB
                    self.db.update_job_metadata(
                        job.id,
                        triage_status=t_res.status.value,
                        triage_reason=t_res.reason,
                    )

                    # Handle CLOSED postings
                    if t_res.status == TriageStatus.CLOSED:
                        print(f"[JOB {job.id[:8]}] ❌ Posting is CLOSED ({t_res.reason}).")
                        self.db.update_job_status(job.id, JobStatus.REJECTED, extra_data={"closed_reason": t_res.reason})
                        continue

                    # Handle DEAD URLs
                    if t_res.status == TriageStatus.DEAD:
                        print(f"[JOB {job.id[:8]}] ❌ Target URL is DEAD ({t_res.reason}).")
                        self.db.update_job_status(job.id, JobStatus.FAILED, extra_data={"error": t_res.reason})
                        continue

                    # Handle LOGIN WALL (Needs Human handoff)
                    if t_res.status == TriageStatus.LOGIN_WALL:
                        print(f"[JOB {job.id[:8]}] 🔒 Login wall encountered -> Transitioning to NEEDS_HUMAN ('continue here' ready).")
                        self.db.update_job_status(
                            job.id,
                            JobStatus.NEEDS_HUMAN,
                            extra_data={"reason": "LOGIN_WALL", "details": t_res.reason},
                        )
                        continue

                    # Handle LANDING PAGE: 1-hop Apply button navigation through SSRF gate
                    current_url = url
                    if t_res.status == TriageStatus.LANDING_PAGE:
                        print(f"[JOB {job.id[:8]}] 🚀 Landing page detected. Following Apply button...")
                        hop_success, dest_url, new_triage, hop_msg = follow_apply_button(page, t_res, url)
                        if hop_success and new_triage and dest_url:
                            current_url = dest_url
                            t_res = new_triage
                            t_res.company = company
                            t_res.role = role
                            print(f"[JOB {job.id[:8]}] Landed on destination: {current_url} ({t_res.status.value})")
                            self.db.update_job_metadata(job.id, triage_status=t_res.status.value, triage_reason=hop_msg)
                        else:
                            print(f"[JOB {job.id[:8]}] Could not navigate to application form: {hop_msg}")
                            self.db.update_job_status(job.id, JobStatus.NEEDS_HUMAN, extra_data={"reason": hop_msg})
                            continue

                    # If not a FORM after hopper, skip to next
                    if t_res.status != TriageStatus.FORM:
                        if t_res.status == TriageStatus.LOGIN_WALL:
                            self.db.update_job_status(job.id, JobStatus.NEEDS_HUMAN, extra_data={"reason": "LOGIN_WALL"})
                        continue

                    # 2. Extract DOM & Form Fields
                    extraction = extract_form_dom(page)

                    if extraction.has_captcha or extraction.has_login_or_password:
                        print(f"[JOB {job.id[:8]}] CAPTCHA / 2FA detected -> NEEDS_HUMAN")
                        self.db.update_job_status(
                            job.id,
                            JobStatus.NEEDS_HUMAN,
                            extra_data={"reason": "CAPTCHA / Security challenge detected"},
                        )
                        continue

                    # Register form action URL with route guard to prevent GET/POST leakage
                    route_guard.register_form_action(extraction.form_action or "")

                    # 3. Mapping: Specialized Adapters + Tier 1 + Answers Bank + Tier 2 LLM
                    mapping_res: MappingPipelineResult = self.mapping_engine.process_form_fields(
                        current_url, extraction.fields, profile, html=page.content()
                    )

                    platform = mapping_res.platform or "generic"
                    self.db.update_job_metadata(job.id, platform=platform)

                    if mapping_res.has_denylisted_fields:
                        print(f"[JOB {job.id[:8]}] Sensitive denylist fields detected -> NEEDS_HUMAN")
                        self.db.update_job_status(
                            job.id,
                            JobStatus.NEEDS_HUMAN,
                            extra_data={"denylist_reasons": mapping_res.denylist_reasons},
                        )
                        continue

                    # 4. Tailoring & No-Fabrication Check for free-text answers
                    tailored = tailor_application(profile, company or "Company", role or "Role")
                    if not tailored.is_grounded:
                        print(f"[JOB {job.id[:8]}] ⚠️ Tailored draft has unverified claims: {tailored.unverified_claims}")

                    # 5. Dry-Run Mode Report
                    if self.dry_run:
                        dry_report = build_dry_run_report(
                            job_id=job.id,
                            url=current_url,
                            mapped_fields=mapping_res.mapped_fields,
                            company=company,
                            role=role,
                        )
                        console.print(dry_report.to_rich_table())
                        self.db.update_job_status(
                            job.id,
                            JobStatus.FILLED,
                            extra_data={"dry_run_report": dry_report.model_dump()},
                        )
                        continue

                    # 6. Populate form fields under sandbox lock
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

                    # 7. Capture snapshot & live screenshot
                    field_selectors = {m.field_id: m.selector for m in mapping_res.mapped_fields}
                    live_vals, snap_hash, screenshot_path = capture_form_snapshot(page, job.id, field_selectors)

                    stage_data = {
                        "mapped_fields": [m.model_dump() for m in mapping_res.mapped_fields],
                        "field_selectors": field_selectors,
                        "fill_summary": fill_summary.model_dump(),
                        "tailored_draft": tailored.model_dump(),
                        "platform": platform,
                    }

                    target_status = JobStatus.NEEDS_HUMAN if mapping_res.needs_human else JobStatus.AWAITING_APPROVAL
                    self.db.update_job_status(
                        job.id,
                        target_status,
                        extra_data=stage_data,
                        approved_hash=snap_hash,
                        screenshot_path=screenshot_path,
                    )

                    review_link = f"http://{settings.review_server_host}:{settings.review_server_port}"
                    notify_job_awaiting_approval(job.id, current_url, review_link)

                    print(f"[JOB {job.id[:8]}] Pre-filled & locked! Status: {target_status.value}")
                    print(f"             Platform: {platform.upper()} | Hash: {snap_hash[:16]}...")

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

        # Display Triage Summary Table in terminal
        if triage_results:
            console.print("\n")
            console.print(generate_triage_table(triage_results))
            summary_stats = summarize_triage(triage_results)
            print(f"\n{summary_stats['summary_text']}")

        return created_job_ids
