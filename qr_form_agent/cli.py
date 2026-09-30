"""Unified CLI for qr-form-agent.

Enforces Requirements 6, 9, 10, 11, 12:
- One command whole flow: qr-form-agent run board.jpg
- Application tracker & exports (CSV, Notion, iCalendar)
- Continue-here headful handoff for login walls and CAPTCHAs
- Saved answers bank inspection and management
- Deadline & opening reminders
"""

import argparse
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
import uvicorn

from qr_form_agent.browser.handoff import execute_continue_here_handoff
from qr_form_agent.config import settings
from qr_form_agent.core.db import Database
from qr_form_agent.core.kill_switch import (
    activate_kill_switch,
    deactivate_kill_switch,
    is_kill_switch_active,
)
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.pipeline import FormAgentPipeline
from qr_form_agent.profile.answers_bank import AnswersBank
from qr_form_agent.profile.extractor import extract_text_from_pdf
from qr_form_agent.profile.storage import load_verified_profile, save_verified_profile
from qr_form_agent.profile.synthesizer import synthesize_profile
from qr_form_agent.review.app import app
from qr_form_agent.submit.submitter import submit_approved_job
from qr_form_agent.tracker.reminders import generate_reminders_table
from qr_form_agent.tracker.tracker import ApplicationTracker

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()


def print_jobs_summary_table(db: Database, job_ids: list[str]) -> None:
    """Renders a styled Rich Table for jobs created/updated during the run."""
    table = Table(
        title="[bold green]Form Agent Job Results[/bold green]",
        caption="Review full screenshots, field diffs, and approve at: http://127.0.0.1:8000",
        header_style="bold green",
    )
    table.add_column("Job ID", style="dim", width=10)
    table.add_column("Company", style="bold cyan")
    table.add_column("Role", style="magenta")
    table.add_column("Platform", justify="center", style="yellow")
    table.add_column("Status", justify="center")
    table.add_column("Snapshot Hash", style="dim", max_width=16, overflow="ellipsis")
    table.add_column("Target URL", style="dim", max_width=30, overflow="ellipsis")

    for jid in job_ids:
        job = db.get_job(jid)
        if not job:
            continue

        status_style = {
            "AWAITING_APPROVAL": "[bold yellow]AWAITING_APPROVAL[/bold yellow]",
            "APPROVED": "[bold green]APPROVED[/bold green]",
            "SUBMITTED": "[bold blue]SUBMITTED[/bold blue]",
            "NEEDS_HUMAN": "[bold red]NEEDS_HUMAN[/bold red]",
            "REJECTED": "[dim red]REJECTED[/dim red]",
            "FAILED": "[bold red]FAILED[/bold red]",
        }.get(job.status.value, job.status.value)

        table.add_row(
            job.id[:8],
            job.company or "[dim]Unknown[/dim]",
            job.role or "[dim]Unknown[/dim]",
            (job.platform or "generic").upper(),
            status_style,
            job.approved_snapshot_hash[:16] if job.approved_snapshot_hash else "-",
            job.url,
        )

    console.print(table)


def main():
    parser = argparse.ArgumentParser(
        prog="qr-form-agent",
        description="Human-in-the-loop agent for QR codes, safe form pre-filling, and verified submission.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Command: run (Requirement 6 - one command whole flow)
    run_p = subparsers.add_parser("run", help="One command for the whole flow: decode, triage, tailor, and pre-fill")
    run_p.add_argument("image", type=Path, help="Path to board or flyer image containing QR codes")
    run_p.add_argument("--resume", "-r", type=Path, help="Path to resume PDF (if profile not already cached)")
    run_p.add_argument("--dry-run", action="store_true", help="Audit mode: verify what would be filled without mutations")
    run_p.add_argument("--auto-confirm", action="store_true", default=True, help="Auto-confirm safe URLs")
    run_p.add_argument("--include-seen", action="store_true", help="Re-scan and process previously seen URLs")

    # Command: scan
    scan_p = subparsers.add_parser("scan", help="Scan QR code image and run fill pipeline")
    scan_p.add_argument("--image", "-i", type=Path, required=True, help="Path to image containing QR codes")
    scan_p.add_argument("--resume", "-r", type=Path, help="Path to resume PDF (if not already verified)")
    scan_p.add_argument("--dry-run", action="store_true", help="Simulate execution without network writes")
    scan_p.add_argument("--auto-confirm", action="store_true", help="Bypass CLI URL confirmation prompt")
    scan_p.add_argument("--include-seen", action="store_true", help="Include previously processed URLs")

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

    # Command: handoff (Requirement 10)
    handoff_p = subparsers.add_parser("handoff", help="Headful 'continue here' takeover for login walls and CAPTCHAs")
    handoff_p.add_argument("--job-id", "-j", required=True, help="ID of job stuck in NEEDS_HUMAN")

    # Command: tracker (Requirement 11)
    tracker_p = subparsers.add_parser("tracker", help="View application tracker or export to CSV/Notion/ICS")
    tracker_p.add_argument("--export-csv", type=Path, help="Export applications to CSV filepath")
    tracker_p.add_argument("--export-notion", type=Path, help="Export applications to Notion-compatible CSV filepath")
    tracker_p.add_argument("--export-ics", type=Path, help="Export deadline and opening reminders to .ics calendar")

    # Command: reminders (Requirement 12)
    subparsers.add_parser("reminders", help="Show upcoming deadlines and opening notices")

    # Command: answers-bank (Requirement 9)
    bank_p = subparsers.add_parser("answers-bank", help="Inspect or update the Saved Answers Bank")
    bank_p.add_argument("--list", action="store_true", default=True, help="List all saved answers")
    bank_p.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set a saved answer key and value")

    # Command: jobs
    jobs_p = subparsers.add_parser("jobs", help="List all jobs and their states")
    jobs_p.add_argument("--status", choices=[s.value for s in JobStatus], help="Filter by status")

    # Command: kill-switch
    kill_p = subparsers.add_parser("kill-switch", help="Activate, deactivate, or check global kill switch")
    kill_p.add_argument("action", choices=["status", "activate", "deactivate"])

    args = parser.parse_args()

    if args.command in ("run", "scan"):
        img = args.image if hasattr(args, "image") else args.image
        pipeline = FormAgentPipeline(dry_run=args.dry_run)
        job_ids = pipeline.process_qr_image(
            image_path=img,
            resume_pdf_path=args.resume,
            auto_confirm_urls=args.auto_confirm,
            include_seen=args.include_seen if hasattr(args, "include_seen") else False,
        )
        if job_ids:
            print_jobs_summary_table(pipeline.db, job_ids)
            print(f"\n✨ Flow complete! {len(job_ids)} jobs processed.")
            print(f"👉 Review, edit, and approve at: http://127.0.0.1:8000")
        else:
            print("\nPipeline finished. No new jobs were created.")

    elif args.command == "handoff":
        db = Database()
        success, updated_job, msg = execute_continue_here_handoff(args.job_id, db)
        if success:
            print(f"\n✔ {msg}")
            print(f"Job {args.job_id} is now in state: {updated_job.status.value}")
        else:
            print(f"\n❌ {msg}")

    elif args.command == "tracker":
        tracker = ApplicationTracker()
        if args.export_csv:
            p = tracker.export_to_csv(args.export_csv)
            print(f"Exported CSV to: {p}")
        elif args.export_notion:
            p = tracker.export_to_notion_csv(args.export_notion)
            print(f"Exported Notion CSV to: {p}")
        elif args.export_ics:
            p = tracker.export_reminders_ics(args.export_ics)
            print(f"Exported iCalendar reminders to: {p}")
        else:
            jobs = tracker.get_all_applications()
            print_jobs_summary_table(tracker.db, [j.id for j in jobs])

    elif args.command == "reminders":
        db = Database()
        jobs = db.list_jobs()
        console.print(generate_reminders_table(jobs))

    elif args.command == "answers-bank":
        bank = AnswersBank()
        if args.set:
            k, v = args.set
            item = bank.set_answer(k, v)
            print(f"✔ Saved answer for '{item.key}': {item.value}")
        else:
            table = Table(title="[bold magenta]Saved Answers Bank[/bold magenta]", header_style="bold magenta")
            table.add_column("Key", style="bold cyan")
            table.add_column("Category", style="yellow")
            table.add_column("Question", style="white")
            table.add_column("Saved Value", style="bold green")
            for item in bank.all_answers():
                table.add_row(item.key, item.category, item.question_text, item.value)
            console.print(table)

    elif args.command == "extract-profile":
        print(f"Extracting text from {args.resume}...")
        text = extract_text_from_pdf(args.resume)
        print("Synthesizing profile with schema...")
        profile = synthesize_profile(text)
        profile.resume_file_path = str(args.resume.resolve())
        saved_path = save_verified_profile(profile)
        print(f"Successfully saved verified profile to: {saved_path}")
        print("\nExtracted Profile Summary:")
        print(profile.model_dump_json(indent=2))

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
        print_jobs_summary_table(db, [j.id for j in jobs])

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
