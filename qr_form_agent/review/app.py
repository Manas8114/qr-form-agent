"""FastAPI human review application and Frontend Control Center backend."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from qr_form_agent.browser.stepper import launch_headful_takeover
from qr_form_agent.config import settings
from qr_form_agent.core.db import Database, JobRecord
from qr_form_agent.core.kill_switch import (
    activate_kill_switch,
    deactivate_kill_switch,
    is_kill_switch_active,
)
from qr_form_agent.core.state_machine import JobStatus
from qr_form_agent.fill.snapshot import compute_snapshot_hash
from qr_form_agent.mapping.cache import MappingCache
from qr_form_agent.profile.extractor import extract_text_from_pdf
from qr_form_agent.profile.schema import Profile
from qr_form_agent.profile.storage import load_verified_profile, save_verified_profile
from qr_form_agent.profile.synthesizer import synthesize_profile
from qr_form_agent.submit.submitter import submit_approved_job

logger = logging.getLogger(__name__)

app = FastAPI(title="QR Form Agent - Frontend Control Center", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


class SubmitRequest(BaseModel):
    dry_run: Optional[bool] = None


# -------------------------------------------------------------
# System Stats & Control Center
# -------------------------------------------------------------

@app.get("/api/stats")
def get_system_stats():
    """Returns aggregated pipeline metrics and operational status."""
    all_jobs = db.list_jobs()
    counts = {s.value: 0 for s in JobStatus}
    for j in all_jobs:
        counts[j.status.value] = counts.get(j.status.value, 0) + 1

    return {
        "total_jobs": len(all_jobs),
        "counts": counts,
        "kill_switch_active": is_kill_switch_active(),
        "dry_run_mode": settings.dry_run,
        "confidence_threshold": settings.confidence_threshold,
    }


@app.post("/api/kill-switch/toggle")
def toggle_kill_switch(activate: bool = Form(...), reason: str = Form("Dashboard operator toggle")):
    if activate:
        activate_kill_switch(reason)
    else:
        deactivate_kill_switch()
    return {"kill_switch_active": is_kill_switch_active()}


# -------------------------------------------------------------
# Profile Management
# -------------------------------------------------------------

@app.get("/api/profile")
def get_profile():
    profile = load_verified_profile()
    if not profile:
        return {"exists": False, "profile": None}
    return {"exists": True, "profile": profile.model_dump()}


@app.post("/api/profile")
def update_profile(profile_data: Dict[str, Any]):
    try:
        profile = Profile.model_validate(profile_data)
        saved_path = save_verified_profile(profile)
        return {"success": True, "saved_path": str(saved_path), "profile": profile.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {e}")


@app.post("/api/profile/upload-resume")
async def upload_resume_pdf(file: UploadFile = File(...)):
    """Uploads and parses a new resume PDF, generating verified profile."""
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = upload_dir / file.filename

    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)

    text = extract_text_from_pdf(target_path)
    profile = synthesize_profile(text)
    profile.resume_file_path = str(target_path.resolve())
    save_verified_profile(profile)

    return {
        "success": True,
        "filename": file.filename,
        "profile": profile.model_dump(),
    }


# -------------------------------------------------------------
# QR Code Pipeline Launchpad
# -------------------------------------------------------------

@app.post("/api/pipeline/scan-image")
async def scan_qr_image(file: UploadFile = File(...), auto_confirm: bool = Form(True)):
    """Uploads an image containing QR codes and triggers pipeline processing."""
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = upload_dir / file.filename

    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)

    from qr_form_agent.pipeline import FormAgentPipeline

    pipeline = FormAgentPipeline(db=db)
    created_job_ids = pipeline.process_qr_image(
        image_path=target_path,
        auto_confirm_urls=auto_confirm,
    )

    return {
        "success": True,
        "jobs_created": created_job_ids,
        "count": len(created_job_ids),
    }


# -------------------------------------------------------------
# Jobs & Review
# -------------------------------------------------------------

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


@app.post("/api/jobs/{job_id}/submit")
def execute_submit(job_id: str, req: SubmitRequest = SubmitRequest()):
    try:
        res = submit_approved_job(job_id, db=db, dry_run=req.dry_run)
        return res.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/jobs/{job_id}/takeover")
def trigger_takeover(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        launch_headful_takeover(job.url)
        return {"success": True, "message": "Headful takeover completed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/audit-logs")
def get_all_audit_logs(limit: int = 50):
    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return {
            "logs": [
                {
                    "id": r["id"],
                    "job_id": r["job_id"],
                    "action": r["action"],
                    "actor": r["actor"],
                    "payload": json.loads(r["payload_json"]),
                    "timestamp": r["timestamp"],
                }
                for r in rows
            ]
        }


@app.get("/", response_class=HTMLResponse)
def index_page():
    ui_path = Path(__file__).parent / "static" / "index.html"
    if ui_path.exists():
        return HTMLResponse(content=ui_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>QR Form Agent Control Center</h1><p>UI loading...</p>")
