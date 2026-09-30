"""Greenhouse ATS platform adapter.

Enforces Requirement 4:
Specialized field mapping for boards.greenhouse.io and embedded Greenhouse job forms.
"""

import logging
from typing import List, Optional
from urllib.parse import urlparse

from qr_form_agent.adapters.base import BaseATSAdapter
from qr_form_agent.browser.dom_extractor import FormFieldDescriptor
from qr_form_agent.mapping.tier1_rules import MappedField
from qr_form_agent.profile.answers_bank import AnswersBank
from qr_form_agent.profile.schema import Profile

logger = logging.getLogger(__name__)


class GreenhouseAdapter(BaseATSAdapter):
    name = "greenhouse"

    def matches(self, url: str, html: str) -> bool:
        parsed = urlparse(url)
        if "greenhouse.io" in parsed.netloc.lower():
            return True
        html_lower = html.lower()
        if "grnhse_app" in html_lower or 'id="application_form"' in html_lower or "greenhouse-job-board" in html_lower:
            return True
        return False

    def map_fields(
        self,
        fields: List[FormFieldDescriptor],
        profile: Profile,
        answers_bank: Optional[AnswersBank] = None,
    ) -> List[MappedField]:
        results: List[MappedField] = []
        answers_bank = answers_bank or AnswersBank()

        # Split full name into first and last
        name_parts = (profile.full_name or "").split()
        first_name = name_parts[0] if name_parts else None
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else None

        for f in fields:
            name_low = (f.name or "").lower()
            id_low = (f.field_id or "").lower()
            label_low = (f.label or "").lower()
            matched = False

            # First Name
            if id_low == "first_name" or "job_application[first_name]" in name_low or "first name" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="first_name",
                        value=first_name,
                        confidence=0.98,
                        reason="Greenhouse first_name matched",
                    )
                )
                matched = True

            # Last Name
            elif id_low == "last_name" or "job_application[last_name]" in name_low or "last name" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="last_name",
                        value=last_name,
                        confidence=0.98,
                        reason="Greenhouse last_name matched",
                    )
                )
                matched = True

            # Email
            elif id_low == "email" or "job_application[email]" in name_low or f.field_type == "email":
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="email",
                        value=profile.email,
                        confidence=0.99,
                        reason="Greenhouse email matched",
                    )
                )
                matched = True

            # Phone
            elif id_low == "phone" or "job_application[phone]" in name_low or f.field_type == "tel":
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="phone",
                        value=profile.phone,
                        confidence=0.98,
                        reason="Greenhouse phone matched",
                    )
                )
                matched = True

            # Resume upload
            elif f.field_type == "file" or id_low == "resume" or "resume" in name_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="resume_file_path",
                        value=profile.resume_file_path,
                        confidence=0.99,
                        reason="Greenhouse resume upload matched",
                        is_resume_upload=True,
                    )
                )
                matched = True

            # LinkedIn
            elif "linkedin" in id_low or "linkedin" in name_low or "linkedin" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="linkedin_url",
                        value=profile.linkedin_url,
                        confidence=0.95,
                        reason="Greenhouse LinkedIn URL matched",
                    )
                )
                matched = True

            # Website / Portfolio
            elif any(w in id_low or w in name_low or w in label_low for w in ("portfolio", "website", "github")):
                target_key = "github_url" if "github" in (id_low + name_low + label_low) else "portfolio_url"
                val = profile.github_url if target_key == "github_url" else (profile.portfolio_url or profile.github_url)
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key=target_key,
                        value=val,
                        confidence=0.92,
                        reason=f"Greenhouse {target_key} matched",
                    )
                )
                matched = True

            # Location / Address
            elif "location" in name_low or "location" in id_low:
                loc_val = f"{profile.city or ''}, {profile.country or ''}".strip(", ") or None
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="location",
                        value=loc_val,
                        confidence=0.90,
                        reason="Greenhouse location matched",
                    )
                )
                matched = True

            # Check Answers Bank for custom questions
            if not matched:
                search_text = f"{f.label or ''} {f.name or ''}".strip()
                bank_hit = answers_bank.find_answer(search_text)
                if bank_hit:
                    b_key, b_val, b_conf = bank_hit
                    results.append(
                        MappedField(
                            field_id=f.field_id,
                            selector=f.selector,
                            profile_key=f"answers_bank.{b_key}",
                            value=b_val,
                            confidence=b_conf,
                            reason=f"Greenhouse custom question matched Answers Bank: {b_key}",
                        )
                    )
                    matched = True

            # If still unmapped, record as unmapped with 0.0 confidence
            if not matched:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key=None,
                        value=None,
                        confidence=0.0,
                        reason="Unmapped Greenhouse field",
                        flagged_for_review=f.required,
                    )
                )

        return results
