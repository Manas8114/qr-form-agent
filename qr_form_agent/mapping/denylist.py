"""Fail-closed denylist detector for security-sensitive and unfillable fields.

Enforces Hard Requirement 3:
Never auto-fill: password, OTP, CAPTCHA, payment, government ID fields,
or any field with no profile mapping. Denylist fails closed. Such cases -> NEEDS_HUMAN.
"""

import logging
import re
from typing import List, Optional, Tuple
from qr_form_agent.browser.dom_extractor import FormFieldDescriptor

logger = logging.getLogger(__name__)

# Strict regex patterns for sensitive field detection
DENYLIST_PATTERNS = [
    # Passwords & Authentication
    (re.compile(r"password|passwd|pwd|passcode|secret", re.I), "PASSWORD_FIELD"),
    # OTP / 2FA
    (re.compile(r"\b(?:otp|totp|2fa|mfa|verification[-_\s]*code|security[-_\s]*code|one[-_\s]*time)\b", re.I), "OTP_FIELD"),
    # Government IDs
    (re.compile(r"\b(?:ssn|social[-_\s]*security|national[-_\s]*id|aadhaar|passport|tax[-_\s]*id|tin|sin)\b", re.I), "GOVERNMENT_ID_FIELD"),
    # Payment / Banking
    (re.compile(r"\b(?:credit[-_\s]*card|card[-_\s]*number|cvv|cvc|expir(?:y|ation)|cardholder|routing[-_\s]*number|bank[-_\s]*account)\b", re.I), "PAYMENT_FIELD"),
    # CAPTCHA
    (re.compile(r"\b(?:captcha|recaptcha|hcaptcha|turnstile)\b", re.I), "CAPTCHA_FIELD"),
]


def check_denylist_violation(field: FormFieldDescriptor) -> Tuple[bool, Optional[str]]:
    """
    Checks if a field matches any forbidden denylist categories.
    Fails closed on any match.
    """
    # 1. HTML input type check
    if field.field_type.lower() == "password":
        return True, "Input type is password"

    # 2. Autocomplete attribute check
    if field.autocomplete:
        ac = field.autocomplete.lower()
        if any(term in ac for term in ["current-password", "new-password", "one-time-code", "cc-number", "cc-csc"]):
            return True, f"Autocomplete '{field.autocomplete}' is denylisted"

    # 3. Label, name, id, and placeholder text pattern matching
    search_corpus = f"{field.label} {field.name or ''} {field.id or ''} {field.placeholder or ''}"

    for pattern, reason in DENYLIST_PATTERNS:
        if pattern.search(search_corpus):
            return True, f"Field matches denylist category: {reason}"

    return False, None


def inspect_form_for_denylisted_fields(fields: List[FormFieldDescriptor]) -> List[Tuple[FormFieldDescriptor, str]]:
    """
    Scans an entire list of extracted fields.
    Returns list of (field, reason) for all denylisted fields found.
    """
    violations: List[Tuple[FormFieldDescriptor, str]] = []
    for f in fields:
        violates, reason = check_denylist_violation(f)
        if violates:
            violations.append((f, reason or "Denylisted field"))

    return violations
