"""Base class and interface for ATS platform adapters."""

from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel

from qr_form_agent.browser.dom_extractor import FormFieldDescriptor
from qr_form_agent.mapping.tier1_rules import MappedField
from qr_form_agent.profile.answers_bank import AnswersBank
from qr_form_agent.profile.schema import Profile


class BaseATSAdapter(ABC):
    """Abstract Base Class for specialized ATS platform adapters."""

    name: str = "generic"

    @abstractmethod
    def matches(self, url: str, html: str) -> bool:
        """Determines if the current URL or page HTML belongs to this ATS platform."""
        pass

    @abstractmethod
    def map_fields(
        self,
        fields: List[FormFieldDescriptor],
        profile: Profile,
        answers_bank: Optional[AnswersBank] = None,
    ) -> List[MappedField]:
        """Maps fields using platform-specific selector and attribute rules."""
        pass
