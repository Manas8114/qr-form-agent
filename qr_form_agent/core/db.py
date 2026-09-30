"""SQLite database engine and models for job state, fields, tracking, and audit history."""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field

from qr_form_agent.config import settings
from qr_form_agent.core.state_machine import JobStatus, validate_transition

logger = logging.getLogger(__name__)


class JobRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    url: str
    domain: str = ""
    status: JobStatus = JobStatus.QUEUED
    stage_data: Dict[str, Any] = Field(default_factory=dict)
    approved_snapshot_hash: Optional[str] = None
    form_screenshot_path: Optional[str] = None
    confirmation_screenshot_path: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # High-level tracker, label OCR, and triage metadata
    triage_status: Optional[str] = None
    triage_reason: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    deadline: Optional[str] = None
    opening_date: Optional[str] = None
    notes: Optional[str] = None
    platform: Optional[str] = None
    applied_date: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if not self.domain and self.url:
            self.domain = urlparse(self.url).netloc.lower()


class AuditLogRecord(BaseModel):
    id: int
    job_id: str
    action: str
    actor: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path:
            self.db_path = db_path
        else:
            raw_url = settings.database_url
            if raw_url.startswith("sqlite:///"):
                self.db_path = Path(raw_url.replace("sqlite:///", ""))
            else:
                self.db_path = settings.data_dir / "qr_agent.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage_data_json TEXT NOT NULL,
                    approved_snapshot_hash TEXT,
                    form_screenshot_path TEXT,
                    confirmation_screenshot_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    triage_status TEXT,
                    triage_reason TEXT,
                    company TEXT,
                    role TEXT,
                    deadline TEXT,
                    opening_date TEXT,
                    notes TEXT,
                    platform TEXT,
                    applied_date TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_job_id ON audit_logs(job_id)")

            # Safe column additions if migrating from previous schema
            existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            for col in (
                "triage_status", "triage_reason", "company", "role",
                "deadline", "opening_date", "notes", "platform", "applied_date"
            ):
                if col not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
                    except sqlite3.OperationalError:
                        pass

            conn.commit()

    def _row_to_job(self, row: sqlite3.Row) -> JobRecord:
        keys = row.keys()
        return JobRecord(
            id=row["id"],
            url=row["url"],
            domain=row["domain"],
            status=JobStatus(row["status"]),
            stage_data=json.loads(row["stage_data_json"]),
            approved_snapshot_hash=row["approved_snapshot_hash"],
            form_screenshot_path=row["form_screenshot_path"],
            confirmation_screenshot_path=row["confirmation_screenshot_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            triage_status=row["triage_status"] if "triage_status" in keys else None,
            triage_reason=row["triage_reason"] if "triage_reason" in keys else None,
            company=row["company"] if "company" in keys else None,
            role=row["role"] if "role" in keys else None,
            deadline=row["deadline"] if "deadline" in keys else None,
            opening_date=row["opening_date"] if "opening_date" in keys else None,
            notes=row["notes"] if "notes" in keys else None,
            platform=row["platform"] if "platform" in keys else None,
            applied_date=row["applied_date"] if "applied_date" in keys else None,
        )

    def create_job(
        self,
        url: str,
        *,
        company: Optional[str] = None,
        role: Optional[str] = None,
        deadline: Optional[str] = None,
        opening_date: Optional[str] = None,
        notes: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> JobRecord:
        job_id = str(uuid.uuid4())
        domain = urlparse(url).netloc.lower()
        now = datetime.now(timezone.utc).isoformat()
        initial_status = JobStatus.QUEUED

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO jobs (
                    id, url, domain, status, stage_data_json, created_at, updated_at,
                    company, role, deadline, opening_date, notes, platform
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, url, domain, initial_status.value, json.dumps({}), now, now,
                company, role, deadline, opening_date, notes, platform
            ))
            conn.commit()

        self.log_action(job_id, "JOB_CREATED", "SYSTEM", {
            "url": url, "company": company, "role": role
        })
        return self.get_job(job_id)  # type: ignore

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def find_job_by_url(self, url: str) -> Optional[JobRecord]:
        """Finds an existing job record matching the given URL."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def find_duplicate_application(self, company: Optional[str], role: Optional[str]) -> Optional[JobRecord]:
        """Checks if an application has already been submitted or staged for the same company and role."""
        if not company or not role:
            return None
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE LOWER(company) = ? AND LOWER(role) = ? AND status != 'REJECTED'",
                (company.lower().strip(), role.lower().strip()),
            ).fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def list_jobs(self, status: Optional[JobStatus] = None) -> List[JobRecord]:
        with self._get_connection() as conn:
            if status:
                rows = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status.value,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()

            return [self._row_to_job(r) for r in rows]

    def update_job_status(
        self,
        job_id: str,
        new_status: JobStatus,
        actor: str = "SYSTEM",
        extra_data: Optional[Dict[str, Any]] = None,
        approved_hash: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        confirmation_screenshot_path: Optional[str] = None,
    ) -> JobRecord:
        """Updates job status with strict state machine validation and audit logging."""
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")

        validate_transition(job.status, new_status)

        stage_data = job.stage_data
        if extra_data:
            stage_data.update(extra_data)

        approved_snapshot_hash = approved_hash if approved_hash is not None else job.approved_snapshot_hash
        form_screenshot = screenshot_path if screenshot_path is not None else job.form_screenshot_path
        conf_screenshot = confirmation_screenshot_path if confirmation_screenshot_path is not None else job.confirmation_screenshot_path

        now = datetime.now(timezone.utc).isoformat()
        applied_date = job.applied_date
        if new_status == JobStatus.SUBMITTED and not applied_date:
            applied_date = now

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE jobs SET
                    status = ?,
                    stage_data_json = ?,
                    approved_snapshot_hash = ?,
                    form_screenshot_path = ?,
                    confirmation_screenshot_path = ?,
                    applied_date = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                new_status.value,
                json.dumps(stage_data),
                approved_snapshot_hash,
                form_screenshot,
                conf_screenshot,
                applied_date,
                now,
                job_id,
            ))
            conn.commit()

        self.log_action(
            job_id,
            "STATUS_CHANGE",
            actor,
            {"old_status": job.status.value, "new_status": new_status.value, "extra": extra_data},
        )
        return self.get_job(job_id)  # type: ignore

    def update_job_metadata(
        self,
        job_id: str,
        *,
        triage_status: Optional[str] = None,
        triage_reason: Optional[str] = None,
        company: Optional[str] = None,
        role: Optional[str] = None,
        deadline: Optional[str] = None,
        opening_date: Optional[str] = None,
        notes: Optional[str] = None,
        platform: Optional[str] = None,
        applied_date: Optional[str] = None,
        stage_data_updates: Optional[Dict[str, Any]] = None,
    ) -> JobRecord:
        """Updates arbitrary metadata on a job record without changing its core FSM state."""
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")

        now = datetime.now(timezone.utc).isoformat()
        stage_data = job.stage_data
        if stage_data_updates:
            stage_data.update(stage_data_updates)

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE jobs SET
                    triage_status = COALESCE(?, triage_status),
                    triage_reason = COALESCE(?, triage_reason),
                    company = COALESCE(?, company),
                    role = COALESCE(?, role),
                    deadline = COALESCE(?, deadline),
                    opening_date = COALESCE(?, opening_date),
                    notes = COALESCE(?, notes),
                    platform = COALESCE(?, platform),
                    applied_date = COALESCE(?, applied_date),
                    stage_data_json = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                triage_status,
                triage_reason,
                company,
                role,
                deadline,
                opening_date,
                notes,
                platform,
                applied_date,
                json.dumps(stage_data),
                now,
                job_id,
            ))
            conn.commit()

        return self.get_job(job_id)  # type: ignore

    def save_job(self, job: JobRecord) -> JobRecord:
        """Inserts or replaces a JobRecord into the database."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO jobs (
                    id, url, domain, status, stage_data_json, approved_snapshot_hash,
                    form_screenshot_path, confirmation_screenshot_path, created_at, updated_at,
                    triage_status, triage_reason, company, role, deadline, opening_date,
                    notes, platform, applied_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id, job.url, job.domain, job.status.value, json.dumps(job.stage_data),
                job.approved_snapshot_hash, job.form_screenshot_path, job.confirmation_screenshot_path,
                job.created_at, job.updated_at, job.triage_status, job.triage_reason,
                job.company, job.role, job.deadline, job.opening_date, job.notes, job.platform,
                job.applied_date,
            ))
            conn.commit()
        return job

    def log_action(self, job_id: str, action: str, actor: str, payload: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO audit_logs (job_id, action, actor, payload_json, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (job_id, action, actor, json.dumps(payload), now))
            conn.commit()

    def get_audit_logs(self, job_id: Optional[str] = None) -> List[AuditLogRecord]:
        with self._get_connection() as conn:
            if job_id:
                rows = conn.execute(
                    "SELECT * FROM audit_logs WHERE job_id = ? ORDER BY timestamp ASC",
                    (job_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 500"
                ).fetchall()

            return [
                AuditLogRecord(
                    id=r["id"],
                    job_id=r["job_id"],
                    action=r["action"],
                    actor=r["actor"],
                    payload=json.loads(r["payload_json"]),
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]
