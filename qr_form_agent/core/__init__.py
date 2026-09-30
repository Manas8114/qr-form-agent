"""Core package for SQLite state machine, database models, rate limiting, and kill switch."""

from qr_form_agent.core.state_machine import (
    JobStatus,
    InvalidStateTransitionError,
    validate_transition,
)
from qr_form_agent.core.db import Database, JobRecord, AuditLogRecord
from qr_form_agent.core.rate_limiter import DomainRateLimiter
from qr_form_agent.core.kill_switch import (
    is_kill_switch_active,
    activate_kill_switch,
    deactivate_kill_switch,
    enforce_kill_switch,
    KillSwitchTriggeredError,
)

__all__ = [
    "JobStatus",
    "InvalidStateTransitionError",
    "validate_transition",
    "Database",
    "JobRecord",
    "AuditLogRecord",
    "DomainRateLimiter",
    "is_kill_switch_active",
    "activate_kill_switch",
    "deactivate_kill_switch",
    "enforce_kill_switch",
    "KillSwitchTriggeredError",
]
