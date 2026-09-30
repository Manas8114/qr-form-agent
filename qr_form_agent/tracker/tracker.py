"""Application tracker with CSV, Notion, and iCalendar export capabilities.

Enforces Requirements 11 & 12:
Tracks all applications, prevents duplicate applications, monitors deadlines/openings,
and exports structured data to CSV, Notion, and calendar reminders.
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from qr_form_agent.core.db import Database, JobRecord

logger = logging.getLogger(__name__)


class ApplicationTracker:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    def get_all_applications(self) -> List[JobRecord]:
        """Returns all tracked jobs."""
        return self.db.list_jobs()

    def check_duplicate(self, url: str, company: Optional[str] = None, role: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Determines if an application for this URL or Company/Role has already been recorded.
        Returns: (is_duplicate: bool, reason: Optional[str])
        """
        # 1. URL duplicate check
        existing_url_job = self.db.find_job_by_url(url)
        if existing_url_job:
            return True, f"Application URL already tracked (Job ID: {existing_url_job.id}, Status: {existing_url_job.status.value})"

        # 2. Company + Role duplicate check
        if company and role:
            existing_app = self.db.find_duplicate_application(company, role)
            if existing_app:
                return True, f"Existing application found for {company} - {role} (Status: {existing_app.status.value})"

        return False, None

    def export_to_csv(self, filepath: Path) -> Path:
        """Exports all tracked applications to standard CSV."""
        jobs = self.get_all_applications()
        filepath.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "id", "company", "role", "status", "platform",
            "url", "deadline", "opening_date", "applied_date",
            "notes", "confirmation_screenshot_path", "created_at"
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for j in jobs:
                writer.writerow({
                    "id": j.id,
                    "company": j.company or "",
                    "role": j.role or "",
                    "status": j.status.value,
                    "platform": j.platform or "",
                    "url": j.url,
                    "deadline": j.deadline or "",
                    "opening_date": j.opening_date or "",
                    "applied_date": j.applied_date or "",
                    "notes": j.notes or "",
                    "confirmation_screenshot_path": j.confirmation_screenshot_path or "",
                    "created_at": j.created_at,
                })

        logger.info("[TRACKER_EXPORT] Exported %d applications to CSV at %s", len(jobs), filepath)
        return filepath

    def export_to_notion_csv(self, filepath: Path) -> Path:
        """
        Exports applications in Notion database CSV format.
        Properties: Name, Status, Company, Role, Platform, URL, Deadline, Date Applied, Notes.
        """
        jobs = self.get_all_applications()
        filepath.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "Name", "Status", "Company", "Role", "Platform",
            "Job Link", "Deadline", "Date Applied", "Notes"
        ]

        status_notion_map = {
            "SUBMITTED": "Applied",
            "APPROVED": "Ready to Submit",
            "AWAITING_APPROVAL": "Review Needed",
            "NEEDS_HUMAN": "Action Required",
            "REJECTED": "Archived",
            "QUEUED": "To Apply",
            "VISITING": "In Progress",
            "FILLED": "Filled",
            "FAILED": "Failed",
        }

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for j in jobs:
                title = f"{j.company or 'Job'} — {j.role or 'Application'}"
                notion_status = status_notion_map.get(j.status.value, j.status.value)
                writer.writerow({
                    "Name": title,
                    "Status": notion_status,
                    "Company": j.company or "",
                    "Role": j.role or "",
                    "Platform": j.platform or "",
                    "Job Link": j.url,
                    "Deadline": j.deadline or "",
                    "Date Applied": j.applied_date or "",
                    "Notes": j.notes or "",
                })

        logger.info("[NOTION_EXPORT] Exported %d applications in Notion format to %s", len(jobs), filepath)
        return filepath

    def export_reminders_ics(self, filepath: Path) -> Path:
        """
        Exports opening notices and application deadlines as an iCalendar (.ics) file.
        """
        jobs = self.get_all_applications()
        filepath.parent.mkdir(parents=True, exist_ok=True)

        events: List[str] = []
        now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        for j in jobs:
            if not (j.deadline or j.opening_date or j.notes):
                continue

            summary = f"Deadline: {j.company or 'Application'} ({j.role or 'Job'})"
            desc = f"Target URL: {j.url}\\nNotes: {j.notes or 'None'}"
            if j.opening_date:
                summary = f"Opening: {j.company or 'Application'} ({j.role or 'Job'})"

            dt_stamp = now_str
            # Format basic ICS VEVENT
            event_text = f"""BEGIN:VEVENT
UID:{j.id}@qrformagent.local
DTSTAMP:{dt_stamp}
DTSTART:{dt_stamp}
SUMMARY:{summary}
DESCRIPTION:{desc}
URL:{j.url}
STATUS:CONFIRMED
END:VEVENT"""
            events.append(event_text)

        calendar_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//QR Form Agent//Application Deadlines//EN
CALSCALE:GREGORIAN
{"\n".join(events)}
END:VCALENDAR
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(calendar_content)

        logger.info("[ICS_EXPORT] Exported calendar reminders to %s", filepath)
        return filepath
