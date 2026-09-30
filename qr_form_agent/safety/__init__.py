"""Safety module for SSRF prevention, HTTPS enforcement, URL deduplication, and user confirmation."""

from qr_form_agent.safety.url_gate import (
    ValidationResult,
    is_ip_allowed,
    resolve_and_check_host,
    validate_url,
)
from qr_form_agent.safety.dedupe import canonicalize_url, deduplicate_urls
from qr_form_agent.safety.gate import GateReport, run_safety_gate

__all__ = [
    "ValidationResult",
    "is_ip_allowed",
    "resolve_and_check_host",
    "validate_url",
    "canonicalize_url",
    "deduplicate_urls",
    "GateReport",
    "run_safety_gate",
]
