"""Tier 1 deterministic rule-based field mapper.

Uses standard HTML5 autocomplete attributes, input types, and robust regex heuristics
to map form fields to verified profile keys with high confidence.
"""

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from qr_form_agent.browser.dom_extractor import FormFieldDescriptor
from qr_form_agent.profile.schema import Profile


class MappedField(BaseModel):
    field_id: str
    selector: str
    profile_key: Optional[str] = None
    value: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    is_resume_upload: bool = False
    flagged_for_review: bool = False


# HTML5 Autocomplete standard mapping
AUTOCOMPLETE_MAP: Dict[str, str] = {
    "given-name": "first_name",
    "family-name": "last_name",
    "name": "full_name",
    "email": "email",
    "tel": "phone",
    "tel-national": "phone",
    "street-address": "address",
    "address-line1": "address",
    "address-level2": "city",
    "address-level1": "state",
    "postal-code": "postal_code",
    "country": "country",
    "country-name": "country",
    "url": "portfolio_url",
}

# Regex heuristics: (pattern, profile_key, confidence, reason)
HEURISTIC_RULES = [
    # Full Name vs First/Last
    (re.compile(r"\b(?:first[-_\s]*name|given[-_\s]*name|fname)\b", re.I), "first_name", 0.98, "First name heuristic match"),
    (re.compile(r"\b(?:last[-_\s]*name|family[-_\s]*name|surname|lname)\b", re.I), "last_name", 0.98, "Last name heuristic match"),
    (re.compile(r"\b(?:full[-_\s]*name|legal[-_\s]*name|candidate[-_\s]*name|your[-_\s]*name|^name$)\b", re.I), "full_name", 0.95, "Full name heuristic match"),

    # Contact
    (re.compile(r"\b(?:email|e-mail|electronic[-_\s]*mailing)\b", re.I), "email", 0.99, "Email heuristic match"),
    (re.compile(r"\b(?:phone|telephone|mobile|cell)\b", re.I), "phone", 0.98, "Phone heuristic match"),

    # Location
    (re.compile(r"\b(?:street[-_\s]*address|address[-_\s]*line)\b", re.I), "address", 0.92, "Address heuristic match"),
    (re.compile(r"\b(?:city|town)\b", re.I), "city", 0.92, "City heuristic match"),
    (re.compile(r"\b(?:state|province|region)\b", re.I), "state", 0.90, "State heuristic match"),
    (re.compile(r"\b(?:zip[-_\s]*code|postal[-_\s]*code|zip)\b", re.I), "postal_code", 0.95, "Postal code heuristic match"),
    (re.compile(r"\b(?:country)\b", re.I), "country", 0.90, "Country heuristic match"),

    # Links
    (re.compile(r"\b(?:linkedin)\b", re.I), "linkedin_url", 0.99, "LinkedIn heuristic match"),
    (re.compile(r"\b(?:github)\b", re.I), "github_url", 0.99, "GitHub heuristic match"),
    (re.compile(r"\b(?:portfolio|personal[-_\s]*website)\b", re.I), "portfolio_url", 0.95, "Portfolio heuristic match"),

    # Resume Upload
    (re.compile(r"\b(?:resume|cv|curriculum[-_\s]*vitae)\b", re.I), "resume_file_path", 0.98, "Resume attachment match"),

    # Summary / Skills
    (re.compile(r"\b(?:summary|objective|cover[-_\s]*letter|about[-_\s]*yourself)\b", re.I), "summary", 0.88, "Summary heuristic match"),
    (re.compile(r"\b(?:skills|technologies)\b", re.I), "skills", 0.88, "Skills heuristic match"),
]


def map_field_tier1(field: FormFieldDescriptor, profile: Profile) -> Optional[MappedField]:
    """
    Attempts to map a single FormFieldDescriptor to verified profile data using Tier 1 rules.
    Returns MappedField if confident match found, else None.
    """
    flat_profile = profile.to_flat_dict()
    flat_profile["resume_file_path"] = profile.resume_file_path

    # Rule 1: Autocomplete attribute
    if field.autocomplete and field.autocomplete.lower() in AUTOCOMPLETE_MAP:
        key = AUTOCOMPLETE_MAP[field.autocomplete.lower()]
        val = flat_profile.get(key)
        return MappedField(
            field_id=field.field_id,
            selector=field.selector,
            profile_key=key,
            value=val,
            confidence=0.99,
            reason=f"Matched HTML5 autocomplete='{field.autocomplete}'",
            flagged_for_review=(val is None and field.required),
        )

    # Rule 2: HTML input type specificity
    if field.field_type == "email":
        val = flat_profile.get("email")
        return MappedField(
            field_id=field.field_id,
            selector=field.selector,
            profile_key="email",
            value=val,
            confidence=0.98,
            reason="Matched HTML input type='email'",
            flagged_for_review=(val is None and field.required),
        )

    if field.field_type == "tel":
        val = flat_profile.get("phone")
        return MappedField(
            field_id=field.field_id,
            selector=field.selector,
            profile_key="phone",
            value=val,
            confidence=0.95,
            reason="Matched HTML input type='tel'",
            flagged_for_review=(val is None and field.required),
        )

    # Rule 3: Resume file input
    if field.field_type == "file":
        corpus = f"{field.label} {field.name or ''} {field.id or ''}".lower()
        if any(term in corpus for term in ["resume", "cv", "vitae", "document"]):
            return MappedField(
                field_id=field.field_id,
                selector=field.selector,
                profile_key="resume_file_path",
                value=profile.resume_file_path,
                confidence=0.98,
                reason="Matched resume file upload field",
                is_resume_upload=True,
                flagged_for_review=True,  # Always review file uploads
            )

    # Rule 4: Heuristic regex matching against combined corpus
    corpus = f"{field.label} {field.placeholder or ''} {field.name or ''} {field.id or ''}"

    for pattern, key, confidence, reason in HEURISTIC_RULES:
        if pattern.search(corpus):
            val = flat_profile.get(key)
            is_file = (key == "resume_file_path")
            return MappedField(
                field_id=field.field_id,
                selector=field.selector,
                profile_key=key,
                value=val,
                confidence=confidence,
                reason=reason,
                is_resume_upload=is_file,
                flagged_for_review=is_file or (val is None and field.required),
            )

    return None
