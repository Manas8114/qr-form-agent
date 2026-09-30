"""CoreHR ATS platform adapter.

Enforces Requirement 4:
Specialized mapping for CoreHR enterprise and higher-education portals.
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


class CoreHRAdapter(BaseATSAdapter):
    name = "corehr"

    def matches(self, url: str, html: str) -> bool:
        parsed = urlparse(url)
        if "corehr.com" in parsed.netloc.lower():
            return True
        html_lower = html.lower()
        if "corehr" in html_lower or "txt_forename" in html_lower or "core_recruitment" in html_lower:
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
            name_low = (f.name or "").lower()
            id_low = (f.field_id or "").lower()
            label_low = (f.label or "").lower()
            matched = False

            # Forename / First Name
            if "forename" in name_low or "forename" in id_low or "first name" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="first_name",
                        value=first_name,
                        confidence=0.98,
                        reason="CoreHR TXT_FORENAME matched",
                    )
                )
                matched = True

            # Surname / Last Name
            elif "surname" in name_low or "surname" in id_low or "last name" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="last_name",
                        value=last_name,
                        confidence=0.98,
                        reason="CoreHR TXT_SURNAME matched",
                    )
                )
                matched = True

            # Email
            elif "email" in name_low or "email" in id_low or f.field_type == "email":
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="email",
                        value=profile.email,
                        confidence=0.99,
                        reason="CoreHR TXT_EMAIL matched",
                    )
                )
                matched = True

            # Telephone
            elif "tel" in name_low or "phone" in name_low or "telephone" in label_low or f.field_type == "tel":
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="phone",
                        value=profile.phone,
                        confidence=0.98,
                        reason="CoreHR TXT_TEL matched",
                    )
                )
                matched = True

            # Address
            elif "addr" in name_low or "address" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="address",
                        value=profile.address,
                        confidence=0.92,
                        reason="CoreHR address field matched",
                    )
                )
                matched = True

            # Postcode
            elif "postcode" in name_low or "postcode" in id_low or "zip" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="postal_code",
                        value=profile.postal_code,
                        confidence=0.95,
                        reason="CoreHR postcode field matched",
                    )
                )
                matched = True

            # Resume upload
            elif f.field_type == "file" or "upload" in name_low or "cv" in label_low or "resume" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="resume_file_path",
                        value=profile.resume_file_path,
                        confidence=0.99,
                        reason="CoreHR file upload matched",
                        is_resume_upload=True,
                    )
                )
                matched = True

            # Custom questions with Answers Bank
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
                            reason=f"CoreHR question matched Answers Bank: {b_key}",
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
                        reason="Unmapped CoreHR field",
                        flagged_for_review=f.required,
                    )
                )

        return results
