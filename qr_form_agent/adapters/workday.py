"""Workday ATS platform adapter.

Enforces Requirement 4:
Specialized mapping for *.myworkdayjobs.com relying on data-automation-id selectors
and multi-step section handling.
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


class WorkdayAdapter(BaseATSAdapter):
    name = "workday"

    def matches(self, url: str, html: str) -> bool:
        parsed = urlparse(url)
        if "myworkdayjobs.com" in parsed.netloc.lower() or "workday.com" in parsed.netloc.lower():
            return True
        html_lower = html.lower()
        if 'data-automation-id="' in html_lower or "wd-form" in html_lower:
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

        name_parts = (profile.full_name or "").split()
        first_name = name_parts[0] if name_parts else None
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else None

        for f in fields:
            selector_low = (f.selector or "").lower()
            name_low = (f.name or "").lower()
            id_low = (f.field_id or "").lower()
            label_low = (f.label or "").lower()
            matched = False

            # First Name
            if "firstname" in selector_low or "firstname" in name_low or "legalnamesection_firstname" in id_low or "first name" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="first_name",
                        value=first_name,
                        confidence=0.98,
                        reason="Workday legalNameSection_firstName matched",
                    )
                )
                matched = True

            # Last Name
            elif "lastname" in selector_low or "lastname" in name_low or "legalnamesection_lastname" in id_low or "last name" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="last_name",
                        value=last_name,
                        confidence=0.98,
                        reason="Workday legalNameSection_lastName matched",
                    )
                )
                matched = True

            # Email
            elif "email" in selector_low or "email" in id_low or f.field_type == "email":
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="email",
                        value=profile.email,
                        confidence=0.99,
                        reason="Workday email matched",
                    )
                )
                matched = True

            # Phone Number
            elif "phone" in selector_low or "phone" in id_low or "phone-number" in selector_low or f.field_type == "tel":
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="phone",
                        value=profile.phone,
                        confidence=0.98,
                        reason="Workday phone-number matched",
                    )
                )
                matched = True

            # Address Line
            elif "addressline1" in selector_low or "address" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="address",
                        value=profile.address,
                        confidence=0.95,
                        reason="Workday addressSection_addressLine1 matched",
                    )
                )
                matched = True

            # City
            elif "addresssection_city" in selector_low or "city" in selector_low or "city" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="city",
                        value=profile.city,
                        confidence=0.95,
                        reason="Workday addressSection_city matched",
                    )
                )
                matched = True

            # Postal Code / Zip
            elif "postalcode" in selector_low or "postal" in label_low or "zip" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="postal_code",
                        value=profile.postal_code,
                        confidence=0.95,
                        reason="Workday addressSection_postalCode matched",
                    )
                )
                matched = True

            # Resume upload dropzone
            elif f.field_type == "file" or "file-upload" in selector_low or "resume" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="resume_file_path",
                        value=profile.resume_file_path,
                        confidence=0.99,
                        reason="Workday file upload dropzone matched",
                        is_resume_upload=True,
                    )
                )
                matched = True

            # Custom questions matched with Answers Bank
            if not matched:
                search_text = f"{f.label or ''} {f.name or ''} {selector_low}".strip()
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
                            reason=f"Workday question matched Answers Bank: {b_key}",
                        )
                    )
                    matched = True

            if not matched:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key=None,
                        value=None,
                        confidence=0.0,
                        reason="Unmapped Workday field",
                        flagged_for_review=f.required,
                    )
                )

        return results
