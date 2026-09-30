"""FastAPI human review application."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from qr_form_agent.config import settings
from qr_form_agent.core.db import Database, JobRecord
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.fill.snapshot import compute_snapshot_hash
from qr_form_agent.mapping.cache import MappingCache

logger = logging.getLogger(__name__)

app = FastAPI(title="QR Form Agent Review Dashboard", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure directories exist
settings.ensure_data_directories()
screenshots_dir = settings.data_dir / "screenshots"
screenshots_dir.mkdir(parents=True, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(screenshots_dir)), name="screenshots")

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

db = Database()
cache = MappingCache()


class ApprovalRequest(BaseModel):
    edited_fields: Dict[str, Any] = Field(description="Dictionary of field_id to final approved value")


@app.get("/api/jobs")
def get_all_jobs(status: Optional[str] = None):
    filter_status = JobStatus(status) if status else None
    jobs = db.list_jobs(filter_status)
    return {"jobs": [j.model_dump() for j in jobs]}


@app.get("/api/jobs/{job_id}")
def get_job_detail(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    logs = db.get_audit_logs(job_id)
    return {
        "job": job.model_dump(),
        "audit_logs": [l.model_dump() for l in logs],
    }


@app.post("/api/jobs/{job_id}/approve")
def approve_job(job_id: str, request: ApprovalRequest):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in (JobStatus.AWAITING_APPROVAL, JobStatus.NEEDS_HUMAN):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve job in status {job.status.value}. Must be AWAITING_APPROVAL or NEEDS_HUMAN.",
        )

    # Compute cryptographic snapshot hash of approved values
    approved_hash = compute_snapshot_hash(request.edited_fields)

    # Record approved field mappings in domain cache for future visits
    domain = job.domain
    for field_id, val in request.edited_fields.items():
        if val:
            sig = cache.compute_field_signature("input", "text", field_id, field_id)
            cache.record_approved_mapping(domain, sig, field_id)

    updated_stage_data = job.stage_data
    updated_stage_data["approved_values"] = request.edited_fields

    updated_job = db.update_job_status(
        job_id=job_id,
        new_status=JobStatus.APPROVED,
        actor="HUMAN_OPERATOR",
        extra_data=updated_stage_data,
        approved_hash=approved_hash,
    )

    return {
        "success": True,
        "job_id": job_id,
        "status": updated_job.status.value,
        "approved_snapshot_hash": approved_hash,
    }


@app.post("/api/jobs/{job_id}/reject")
def reject_job(job_id: str, reason: str = "Rejected by human reviewer"):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    updated_job = db.update_job_status(
        job_id=job_id,
        new_status=JobStatus.REJECTED,
        actor="HUMAN_OPERATOR",
        extra_data={"rejection_reason": reason},
    )

    return {"success": True, "job_id": job_id, "status": updated_job.status.value}


@app.get("/", response_class=HTMLResponse)
def index_page():
    ui_path = Path(__file__).parent / "static" / "index.html"
    if ui_path.exists():
        return HTMLResponse(content=ui_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>QR Form Agent Review Dashboard</h1><p>UI loading...</p>")
