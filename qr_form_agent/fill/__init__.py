"""Form filling package with route guards, safe value population, and snapshot hashing."""

from qr_form_agent.fill.route_guard import FillRouteGuard, BlockedRequest
from qr_form_agent.fill.uploader import upload_resume_if_requested
from qr_form_agent.fill.filler import FillItem, FillSummary, fill_form_fields, populate_single_field
from qr_form_agent.fill.dry_run_report import DryRunReport, DryRunFieldReport, build_dry_run_report
from qr_form_agent.fill.snapshot import (
    compute_snapshot_hash,
    extract_live_form_values,
    capture_form_snapshot,
)

__all__ = [
    "FillRouteGuard",
    "BlockedRequest",
    "upload_resume_if_requested",
    "FillItem",
    "FillSummary",
    "fill_form_fields",
    "populate_single_field",
    "compute_snapshot_hash",
    "extract_live_form_values",
    "capture_form_snapshot",
    "DryRunReport",
    "DryRunFieldReport",
    "build_dry_run_report",
]
