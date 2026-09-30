"""Registry for discovering and selecting ATS platform adapters."""

import logging
from typing import List, Optional

from qr_form_agent.adapters.base import BaseATSAdapter
from qr_form_agent.adapters.corehr import CoreHRAdapter
from qr_form_agent.adapters.greenhouse import GreenhouseAdapter
from qr_form_agent.adapters.lever import LeverAdapter
from qr_form_agent.adapters.workday import WorkdayAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    def __init__(self, adapters: Optional[List[BaseATSAdapter]] = None):
        self.adapters: List[BaseATSAdapter] = adapters or [
            GreenhouseAdapter(),
            LeverAdapter(),
            WorkdayAdapter(),
            CoreHRAdapter(),
        ]

    def find_adapter(self, url: str, html: str = "") -> Optional[BaseATSAdapter]:
        """Returns the first adapter matching the given URL or HTML content."""
        for adapter in self.adapters:
            try:
                if adapter.matches(url, html):
                    logger.info("[ADAPTER_MATCH] Selected specialized adapter '%s' for %s", adapter.name, url)
                    return adapter
            except Exception as e:
                logger.debug("Error checking adapter %s: %s", adapter.name, e)

        return None
