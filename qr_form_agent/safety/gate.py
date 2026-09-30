"""Integrated safety gate for batch URL processing, validation, and human confirmation."""

import logging
from typing import Callable, List, Optional, Tuple
from pydantic import BaseModel, Field

from qr_form_agent.safety.dedupe import deduplicate_urls
from qr_form_agent.safety.url_gate import ValidationResult, validate_url

logger = logging.getLogger(__name__)


class GateReport(BaseModel):
    approved_urls: List[str] = Field(default_factory=list, description="URLs approved for visitation")
    rejected_urls: List[Tuple[str, str]] = Field(default_factory=list, description="Tuple of (url, rejection_reason)")
    user_confirmed: bool = Field(default=False, description="Whether explicit user confirmation was granted")


def run_safety_gate(
    raw_urls: List[str],
    resolve_redirects: bool = True,
    auto_confirm: bool = False,
    confirmation_callback: Optional[Callable[[List[str]], bool]] = None,
) -> GateReport:
    """
    Executes the full URL safety gate:
      1. HTTPS check
      2. DNS resolution and SSRF defense (private, loopback, link-local blocks)
      3. Redirect chain verification
      4. Deduplication
      5. Full URL list presentation and operator confirmation
    """
    # Step 1-3: Validate all URLs
    valid_urls: List[str] = []
    rejected: List[Tuple[str, str]] = []

    for raw in raw_urls:
        res: ValidationResult = validate_url(raw, resolve_redirects=resolve_redirects)
        if res.is_safe and res.final_url:
            valid_urls.append(res.final_url)
        else:
            rejected.append((raw, res.error_reason or "Unknown rejection reason"))
            logger.warning("Rejected unsafe URL %s: %s", raw, res.error_reason)

    # Step 4: Deduplicate safe URLs
    deduped_approved = deduplicate_urls(valid_urls)

    if not deduped_approved:
        return GateReport(
            approved_urls=[],
            rejected_urls=rejected,
            user_confirmed=False,
        )

    # Step 5: Operator confirmation gate
    confirmed = False
    if auto_confirm:
        confirmed = True
    elif confirmation_callback:
        confirmed = confirmation_callback(deduped_approved)
    else:
        # Default CLI prompt
        print("\n" + "=" * 60)
        print(" [URL SAFETY GATE] Found the following verified target URLs:")
        for idx, u in enumerate(deduped_approved, 1):
            print(f"   {idx}. {u}")
        print("=" * 60)
        try:
            resp = input("Proceed with these URLs? [y/N]: ").strip().lower()
            confirmed = resp in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            confirmed = False

    return GateReport(
        approved_urls=deduped_approved if confirmed else [],
        rejected_urls=rejected,
        user_confirmed=confirmed,
    )
