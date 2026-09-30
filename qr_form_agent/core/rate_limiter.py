"""Per-domain rate limiter using sliding window timestamps."""

import logging
import time
from typing import Dict
from urllib.parse import urlparse
from qr_form_agent.config import settings

logger = logging.getLogger(__name__)


class DomainRateLimiter:
    """Enforces minimum delay interval between requests to the same domain."""

    def __init__(self, default_interval: float = 2.0):
        self.default_interval = default_interval
        self._last_access: Dict[str, float] = {}

    def wait_for_domain(self, url: str) -> None:
        """Blocks until minimum delay interval has elapsed for the domain."""
        domain = urlparse(url).netloc.lower()
        now = time.time()
        last = self._last_access.get(domain, 0.0)
        elapsed = now - last

        interval = settings.rate_limit_per_domain_seconds or self.default_interval
        if elapsed < interval:
            wait_time = interval - elapsed
            logger.info("Rate limiting domain %s: sleeping for %.2f seconds", domain, wait_time)
            time.sleep(wait_time)

        self._last_access[domain] = time.time()
