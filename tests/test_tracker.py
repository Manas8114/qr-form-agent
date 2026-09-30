"""Tests for Application Tracker, Reminders, Duplicate Detection, and Batch Re-Scan Diff.

Enforces Requirements 11, 12, & 13:
- Application tracking and duplicate prevention (by URL and Company+Role).
- Export to CSV, Notion-compatible CSV, and iCalendar (.ics).
- Batch re-scan URL diffing against existing DB records.
"""

from pathlib import Path
import pytest

from qr_form_agent.core.db import Database, JobRecord, JobStatus
from qr_form_agent.safety.dedupe import diff_against_existing_urls
from qr_form_agent.tracker.reminders import generate_reminders_table
from qr_form_agent.tracker.tracker import ApplicationTracker


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_tracker.db"
    return Database(db_path=db_file)


def test_tracker_duplicate_detection(temp_db):
    """Accurately detects duplicate applications by URL and Company+Role."""
    tracker = ApplicationTracker(db=temp_db)

    # Insert existing job
    job = JobRecord(
        url="https://careers.google.com/jobs/results/123",
        company="Google",
        role="Software Engineer",
        status=JobStatus.QUEUED,
        deadline="2026-11-30",
    )
    temp_db.save_job(job)

    # 1. Exact URL duplicate check
    is_dup_url, reason_url = tracker.check_duplicate(
        url="https://careers.google.com/jobs/results/123",
        company="Other Company",
        role="Other Role",
    )
    assert is_dup_url is True
    assert "already tracked" in reason_url

    # 2. Company + Role duplicate check
    is_dup_role, reason_role = tracker.check_duplicate(
        url="https://careers.google.com/another-posting/456",
        company="Google",
        role="Software Engineer",
    )
    assert is_dup_role is True
    assert "Existing application found" in reason_role

    # 3. Fresh job
    is_dup_fresh, _ = tracker.check_duplicate(
        url="https://stripe.com/jobs/789",
        company="Stripe",
        role="Frontend Engineer",
    )
    assert is_dup_fresh is False


def test_tracker_csv_export(temp_db, tmp_path: Path):
    """Exports structured applications to standard CSV format."""
    tracker = ApplicationTracker(db=temp_db)

    job1 = JobRecord(
        url="https://jobs.apple.com/1",
        company="Apple",
        role="iOS Engineer",
        status=JobStatus.SUBMITTED,
        applied_date="2026-09-30",
    )
    temp_db.save_job(job1)

    csv_path = tmp_path / "applications.csv"
    exported = tracker.export_to_csv(csv_path)

    assert exported.exists()
    content = exported.read_text(encoding="utf-8")
    assert "company,role,status" in content
    assert "Apple" in content
    assert "iOS Engineer" in content
    assert "SUBMITTED" in content


def test_tracker_notion_export(temp_db, tmp_path: Path):
    """Exports applications in Notion database CSV format with mapped properties."""
    tracker = ApplicationTracker(db=temp_db)

    job1 = JobRecord(
        url="https://jobs.palantir.com/1",
        company="Palantir",
        role="Deployment Strategist",
        status=JobStatus.APPROVED,
        deadline="2026-12-15",
    )
    temp_db.save_job(job1)

    notion_path = tmp_path / "notion_jobs.csv"
    exported = tracker.export_to_notion_csv(notion_path)

    assert exported.exists()
    content = exported.read_text(encoding="utf-8")
    assert "Name,Status,Company,Role,Platform,Job Link,Deadline" in content
    assert "Palantir — Deployment Strategist" in content
    assert "Ready to Submit" in content


def test_tracker_calendar_ics_export(temp_db, tmp_path: Path):
    """Exports deadlines and opening dates to standard iCalendar .ics format."""
    tracker = ApplicationTracker(db=temp_db)

    job_with_deadline = JobRecord(
        url="https://jobs.bloomberg.com/1",
        company="Bloomberg",
        role="Data Engineer",
        status=JobStatus.QUEUED,
        deadline="2026-10-15",
        notes="Horizon opens in December",
    )
    temp_db.save_job(job_with_deadline)

    ics_path = tmp_path / "reminders.ics"
    exported = tracker.export_reminders_ics(ics_path)

    assert exported.exists()
    content = exported.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in content
    assert "BEGIN:VEVENT" in content
    assert "SUMMARY:Deadline: Bloomberg (Data Engineer)" in content
    assert "END:VCALENDAR" in content


def test_batch_rescan_url_diff():
    """Diffs discovered QR URLs against existing database URLs to identify only new postings."""
    discovered = [
        "https://jobs.example.com/posting-1",
        "https://jobs.example.com/posting-2",
        "https://jobs.example.com/posting-3",
    ]

    existing = {
        "https://jobs.example.com/posting-1",
        "https://jobs.other.com/old-job",
    }

    new_urls, seen_urls = diff_against_existing_urls(discovered, existing)

    assert len(new_urls) == 2
    assert "https://jobs.example.com/posting-2" in new_urls
    assert "https://jobs.example.com/posting-3" in new_urls
    assert len(seen_urls) == 1
    assert "https://jobs.example.com/posting-1" in seen_urls


def test_generate_reminders_table(temp_db):
    """Renders formatted Rich table for upcoming deadlines and opening notices."""
    job = JobRecord(
        url="https://careers.amazon.com/1",
        company="Amazon",
        role="SDE I",
        status=JobStatus.QUEUED,
        deadline="2026-11-01",
        opening_date="2026-10-15",
        notes="Requires online assessment before interview",
    )
    temp_db.save_job(job)

    table = generate_reminders_table(temp_db.list_jobs())
    assert table is not None
    assert len(table.rows) == 1
