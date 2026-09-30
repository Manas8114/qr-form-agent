"""Lever ATS platform adapter.

Enforces Requirement 4:
Specialized field mapping for jobs.lever.co and Lever application forms.
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


class LeverAdapter(BaseATSAdapter):
    name = "lever"

    def matches(self, url: str, html: str) -> bool:
        parsed = urlparse(url)
        if "lever.co" in parsed.netloc.lower():
            return True
        html_lower = html.lower()
        if "lever-application" in html_lower or 'id="application-form"' in html_lower:
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

        for f in fields:
            name_low = (f.name or "").lower()
            id_low = (f.field_id or "").lower()
            label_low = (f.label or "").lower()
            matched = False

            # Full Name
            if name_low == "name" or id_low == "name" or "full name" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="full_name",
                        value=profile.full_name,
                        confidence=0.99,
                        reason="Lever name field matched",
                    )
                )
                matched = True

            # Email
            elif name_low == "email" or id_low == "email" or f.field_type == "email":
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="email",
                        value=profile.email,
                        confidence=0.99,
                        reason="Lever email field matched",
                    )
                )
                matched = True

            # Phone
            elif name_low == "phone" or id_low == "phone" or f.field_type == "tel":
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="phone",
                        value=profile.phone,
                        confidence=0.98,
                        reason="Lever phone field matched",
                    )
                )
                matched = True

            # Current company or university (org)
            elif name_low == "org" or "current company" in label_low or "employer" in label_low:
                current_org = getattr(profile, "current_company", None)
                if not current_org and profile.experience and len(profile.experience) > 0:
                    current_org = profile.experience[0].company
                elif not current_org and profile.education and len(profile.education) > 0:
                    current_org = profile.education[0].institution
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="current_company",
                        value=current_org,
                        confidence=0.90,
                        reason="Lever org field matched",
                    )
                )
                matched = True

            # URLs: LinkedIn
            elif "urls[linkedin]" in name_low or "linkedin" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="linkedin_url",
                        value=profile.linkedin_url,
                        confidence=0.98,
                        reason="Lever LinkedIn URL matched",
                    )
                )
                matched = True

            # URLs: GitHub
            elif "urls[github]" in name_low or "github" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="github_url",
                        value=profile.github_url,
                        confidence=0.98,
                        reason="Lever GitHub URL matched",
                    )
                )
                matched = True

            # URLs: Portfolio
            elif "urls[portfolio]" in name_low or "portfolio" in label_low or "website" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="portfolio_url",
                        value=profile.portfolio_url or profile.github_url,
                        confidence=0.95,
                        reason="Lever Portfolio URL matched",
                    )
                )
                matched = True

            # Resume upload
            elif f.field_type == "file" or "resume" in name_low or "resume" in id_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="resume_file_path",
                        value=profile.resume_file_path,
                        confidence=0.99,
                        reason="Lever resume file input matched",
                        is_resume_upload=True,
                    )
                )
                matched = True

            # Comments / Additional info
            elif name_low == "comments" or "additional" in label_low or "comments" in label_low:
                results.append(
                    MappedField(
                        field_id=f.field_id,
                        selector=f.selector,
                        profile_key="summary",
                        value=profile.summary,
                        confidence=0.88,
                        reason="Lever comments field matched profile summary",
                    )
                )
                matched = True

            # Custom questions checked with AnswersBank
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
                            reason=f"Lever custom question matched Answers Bank: {b_key}",
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
                        reason="Unmapped Lever field",
                        flagged_for_review=f.required,
                    )
                )

        return results
