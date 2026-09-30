"""Unified form field mapping engine.

Coordinates:
1. Fail-closed denylist check (password, OTP, SSN, payment, CAPTCHA -> flags NEEDS_HUMAN)
2. SQLite per-domain approved mapping cache lookup
3. Tier 1 deterministic rules (autocomplete, input type, label regex)
4. Tier 2 zero-tool LLM mapper for remaining unmapped fields
5. Confidence aggregation and review flagging
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field

from qr_form_agent.browser.dom_extractor import FormFieldDescriptor
from qr_form_agent.config import settings
from qr_form_agent.mapping.cache import MappingCache
from qr_form_agent.mapping.denylist import inspect_form_for_denylisted_fields
from qr_form_agent.mapping.tier1_rules import MappedField, map_field_tier1
from qr_form_agent.mapping.tier2_llm import map_fields_with_llm
from qr_form_agent.profile.answers_bank import AnswersBank
from qr_form_agent.profile.schema import Profile

logger = logging.getLogger(__name__)


class MappingPipelineResult(BaseModel):
    mapped_fields: List[MappedField] = Field(default_factory=list)
    has_denylisted_fields: bool = False
    denylist_reasons: List[str] = Field(default_factory=list)
    needs_human: bool = False
    average_confidence: float = 0.0
    platform: Optional[str] = None


class MappingEngine:
    def __init__(
        self,
        cache: Optional[MappingCache] = None,
        answers_bank: Optional[AnswersBank] = None,
        adapter_registry: Optional[Any] = None,
    ):
        self.cache = cache or MappingCache()
        self.answers_bank = answers_bank or AnswersBank()
        if adapter_registry is None:
            from qr_form_agent.adapters.registry import AdapterRegistry
            self.adapter_registry = AdapterRegistry()
        else:
            self.adapter_registry = adapter_registry

    def process_form_fields(
        self,
        url: str,
        fields: List[FormFieldDescriptor],
        profile: Profile,
        html: str = "",
    ) -> MappingPipelineResult:
        """
        Executes the entire mapping pipeline on extracted form fields.
        """
        domain = urlparse(url).netloc.lower()
        flat_profile = profile.to_flat_dict()
        flat_profile["resume_file_path"] = profile.resume_file_path

        # Step 1: Check Denylist
        denylist_violations = inspect_form_for_denylisted_fields(fields)
        if denylist_violations:
            reasons = [f"{f.field_id}: {r}" for f, r in denylist_violations]
            logger.warning("Form at %s triggered denylist: %s", url, reasons)
            return MappingPipelineResult(
                mapped_fields=[],
                has_denylisted_fields=True,
                denylist_reasons=reasons,
                needs_human=True,
                average_confidence=0.0,
            )

        mapped_results: Dict[str, MappedField] = {}
        unmapped_fields: List[FormFieldDescriptor] = []

        # Step 2: Check for specialized ATS Platform Adapter (Workday, Greenhouse, Lever, CoreHR)
        platform_name: Optional[str] = None
        adapter = self.adapter_registry.find_adapter(url, html)
        if adapter:
            platform_name = adapter.name
            adapter_mapped = adapter.map_fields(fields, profile, self.answers_bank)
            for m in adapter_mapped:
                if m.confidence >= settings.confidence_threshold:
                    mapped_results[m.field_id] = m

        # Step 3: Cache lookup, Tier 1 rules & Answers Bank for remaining fields
        for f in fields:
            if f.field_id in mapped_results:
                continue

            sig = self.cache.compute_field_signature(f.tag_name, f.field_type, f.name, f.label)
            cached_key = self.cache.get_cached_key(domain, sig)

            if cached_key and cached_key in flat_profile:
                val = flat_profile[cached_key]
                mapped_results[f.field_id] = MappedField(
                    field_id=f.field_id,
                    selector=f.selector,
                    profile_key=cached_key,
                    value=val,
                    confidence=0.99,
                    reason="Matched domain mapping cache",
                    is_resume_upload=(cached_key == "resume_file_path"),
                    flagged_for_review=False,
                )
                continue

            # Try Tier 1 rules
            t1 = map_field_tier1(f, profile)
            if t1 and t1.confidence >= settings.confidence_threshold:
                mapped_results[f.field_id] = t1
                continue

            # Try Saved Answers Bank (deterministic, 1.0 confidence, bypasses LLM)
            candidate_text = f"{f.label or ''} {f.name or ''} {f.placeholder or ''}".strip()
            bank_match = self.answers_bank.find_answer(candidate_text)
            if bank_match:
                b_key, b_val, b_conf = bank_match
                mapped_results[f.field_id] = MappedField(
                    field_id=f.field_id,
                    selector=f.selector,
                    profile_key=f"answers_bank.{b_key}",
                    value=b_val,
                    confidence=b_conf,
                    reason=f"Matched Saved Answers Bank: {b_key}",
                    flagged_for_review=False,
                )
            else:
                unmapped_fields.append(f)

        # Step 4: Tier 2 LLM for remaining unmapped fields
        if unmapped_fields:
            t2_results = map_fields_with_llm(unmapped_fields, profile)
            for m in t2_results:
                mapped_results[m.field_id] = m

        # Assemble in original order
        final_list: List[MappedField] = []
        confidences: List[float] = []
        needs_human = False

        for f in fields:
            if f.field_id in mapped_results:
                mf = mapped_results[f.field_id]
                final_list.append(mf)
                confidences.append(mf.confidence)
                if mf.flagged_for_review or (f.required and mf.value is None):
                    needs_human = True

        avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0

        return MappingPipelineResult(
            mapped_fields=final_list,
            has_denylisted_fields=False,
            denylist_reasons=[],
            needs_human=needs_human,
            average_confidence=round(avg_conf, 3),
            platform=platform_name,
        )
