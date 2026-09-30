"""SQLite database engine and models for job state, fields, and audit history."""

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
    id: str
    url: str
    domain: str
    status: JobStatus
    stage_data: Dict[str, Any] = Field(default_factory=dict)
    approved_snapshot_hash: Optional[str] = None
    form_screenshot_path: Optional[str] = None
    confirmation_screenshot_path: Optional[str] = None
    created_at: str
    updated_at: str


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
            # Parse database_url (e.g. sqlite:///./data/qr_agent.db)
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
                    updated_at TEXT NOT NULL
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_job_id ON audit_logs(job_id)")
            conn.commit()

    def create_job(self, url: str) -> JobRecord:
        job_id = str(uuid.uuid4())
        domain = urlparse(url).netloc.lower()
        now = datetime.now(timezone.utc).isoformat()
        initial_status = JobStatus.QUEUED

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO jobs (id, url, domain, status, stage_data_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (job_id, url, domain, initial_status.value, json.dumps({}), now, now))
            conn.commit()

        self.log_action(job_id, "JOB_CREATED", "SYSTEM", {"url": url})
        return self.get_job(job_id)  # type: ignore

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
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
            )

    def list_jobs(self, status: Optional[JobStatus] = None) -> List[JobRecord]:
        with self._get_connection() as conn:
            if status:
                rows = conn.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status.value,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()

            return [
                JobRecord(
                    id=r["id"],
                    url=r["url"],
                    domain=r["domain"],
                    status=JobStatus(r["status"]),
                    stage_data=json.loads(r["stage_data_json"]),
                    approved_snapshot_hash=r["approved_snapshot_hash"],
                    form_screenshot_path=r["form_screenshot_path"],
                    confirmation_screenshot_path=r["confirmation_screenshot_path"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

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

        # Validate state machine rules
        validate_transition(job.status, new_status)

        stage_data = job.stage_data
        if extra_data:
            stage_data.update(extra_data)

        approved_snapshot_hash = approved_hash if approved_hash is not None else job.approved_snapshot_hash
        form_screenshot = screenshot_path if screenshot_path is not None else job.form_screenshot_path
        conf_screenshot = confirmation_screenshot_path if confirmation_screenshot_path is not None else job.confirmation_screenshot_path

        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE jobs SET
                    status = ?,
                    stage_data_json = ?,
                    approved_snapshot_hash = ?,
                    form_screenshot_path = ?,
                    confirmation_screenshot_path = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                new_status.value,
                json.dumps(stage_data),
                approved_snapshot_hash,
                form_screenshot,
                conf_screenshot,
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

    def log_action(self, job_id: str, action: str, actor: str, payload: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO audit_logs (job_id, action, actor, payload_json, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (job_id, action, actor, json.dumps(payload), now))
            conn.commit()

    def get_audit_logs(self, job_id: str) -> List[AuditLogRecord]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_logs WHERE job_id = ? ORDER BY timestamp ASC",
                (job_id,),
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
