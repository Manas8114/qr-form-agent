"""Review module with FastAPI server and Web UI."""

from qr_form_agent.review.notifications import notify_job_awaiting_approval

__all__ = ["notify_job_awaiting_approval"]
