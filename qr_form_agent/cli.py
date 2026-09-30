"""Unified CLI for qr-form-agent."""

import argparse
import sys
from pathlib import Path
import uvicorn

from qr_form_agent.config import settings
from qr_form_agent.core.db import Database
from qr_form_agent.core.kill_switch import (
    activate_kill_switch,
    deactivate_kill_switch,
    is_kill_switch_active,
)
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.pipeline import FormAgentPipeline
from qr_form_agent.profile.extractor import extract_text_from_pdf
from qr_form_agent.profile.storage import load_verified_profile, save_verified_profile
from qr_form_agent.profile.synthesizer import synthesize_profile
from qr_form_agent.review.app import app
from qr_form_agent.submit.submitter import submit_approved_job


def main():
    parser = argparse.ArgumentParser(
        prog="qr-form-agent",
        description="Human-in-the-loop agent for QR codes, safe form pre-filling, and verified submission.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Command: scan
    scan_p = subparsers.add_parser("scan", help="Scan QR code image and run fill pipeline")
    scan_p.add_argument("--image", "-i", type=Path, required=True, help="Path to image containing QR codes")
    scan_p.add_argument("--resume", "-r", type=Path, help="Path to resume PDF (if not already verified)")
    scan_p.add_argument("--dry-run", action="store_true", help="Simulate execution without network writes")
    scan_p.add_argument("--auto-confirm", action="store_true", help="Bypass CLI URL confirmation prompt")

    # Command: extract-profile
    prof_p = subparsers.add_parser("extract-profile", help="Parse resume PDF into verified profile.json")
    prof_p.add_argument("--resume", "-r", type=Path, required=True, help="Path to resume PDF")

    # Command: review
    rev_p = subparsers.add_parser("review", help="Launch FastAPI web review dashboard")
    rev_p.add_argument("--host", default=settings.review_server_host, help="Host address")
    rev_p.add_argument("--port", type=int, default=settings.review_server_port, help="Port number")

    # Command: submit
    sub_p = subparsers.add_parser("submit", help="Submit an approved job")
    sub_p.add_argument("--job-id", "-j", required=True, help="ID of approved job")
    sub_p.add_argument("--dry-run", action="store_true", help="Simulate submit without network write")

    # Command: jobs
    jobs_p = subparsers.add_parser("jobs", help="List all jobs and their states")
    jobs_p.add_argument("--status", choices=[s.value for s in JobStatus], help="Filter by status")

    # Command: kill-switch
    kill_p = subparsers.add_parser("kill-switch", help="Activate, deactivate, or check global kill switch")
    kill_p.add_argument("action", choices=["status", "activate", "deactivate"])

    args = parser.parse_args()

    if args.command == "extract-profile":
        print(f"Extracting text from {args.resume}...")
        text = extract_text_from_pdf(args.resume)
        print("Synthesizing profile with schema...")
        profile = synthesize_profile(text)
        profile.resume_file_path = str(args.resume.resolve())
        saved_path = save_verified_profile(profile)
        print(f"Successfully saved verified profile to: {saved_path}")
        print("\nExtracted Profile Summary:")
        print(profile.model_dump_json(indent=2))

    elif args.command == "scan":
        pipeline = FormAgentPipeline(dry_run=args.dry_run)
        job_ids = pipeline.process_qr_image(
            image_path=args.image,
            resume_pdf_path=args.resume,
            auto_confirm_urls=args.auto_confirm,
        )
        print(f"\nProcessing complete. {len(job_ids)} jobs created/updated.")
        print(f"Launch review dashboard with: qr-form-agent review")

    elif args.command == "review":
        print(f"Starting review server at http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "submit":
        res = submit_approved_job(args.job_id, dry_run=args.dry_run)
        if res.success:
            print(f"Job {args.job_id} successfully submitted!")
            print(f"Receipt: {res.receipt_text}")
        else:
            print(f"Submission failed: {res.error_message}")

    elif args.command == "jobs":
        db = Database()
        filter_status = JobStatus(args.status) if args.status else None
        jobs = db.list_jobs(filter_status)
        print(f"\n{'ID':<38} {'STATUS':<20} {'DOMAIN':<25} {'URL'}")
        print("-" * 100)
        for j in jobs:
            print(f"{j.id:<38} {j.status.value:<20} {j.domain:<25} {j.url}")

    elif args.command == "kill-switch":
        if args.action == "status":
            active = is_kill_switch_active()
            print(f"Global Kill Switch is: {'ACTIVE (HALTED)' if active else 'INACTIVE (NORMAL)'}")
        elif args.action == "activate":
            activate_kill_switch("CLI command")
            print("Global kill switch has been ACTIVATED. All jobs halted.")
        elif args.action == "deactivate":
            deactivate_kill_switch()
            print("Global kill switch has been DEACTIVATED. Resuming normal operations.")


if __name__ == "__main__":
    main()
