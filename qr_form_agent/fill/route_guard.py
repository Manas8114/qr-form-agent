"""Network route guard for fill phase.

Enforces Hard Requirement 1:
During fill phase, abort non-GET requests to form action URLs (and any mutating POST/PUT/DELETE)
via Playwright's page.route.
"""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from playwright.sync_api import Page, Route, Request

logger = logging.getLogger(__name__)


class BlockedRequest(BaseModel):
    url: str
    method: str
    resource_type: str
    reason: str


class FillRouteGuard:
    """
    Manages active route interception on a Playwright Page during the fill phase.
    Unconditionally blocks any POST, PUT, PATCH, or DELETE requests.
    """

    def __init__(self, page: Page):
        self.page = page
        self.blocked_requests: List[BlockedRequest] = []
        self._installed = False

    def install(self) -> None:
        """Installs the route interception guard on the page."""
        if self._installed:
            return

        def _handle_route(route: Route) -> None:
            req: Request = route.request
            method = req.method.upper()

            # Permitted read-only methods
            if method in ("GET", "OPTIONS", "HEAD"):
                route.continue_()
                return

            # Mutating methods are strictly forbidden during the fill phase!
            record = BlockedRequest(
                url=req.url,
                method=method,
                resource_type=req.resource_type,
                reason="Non-GET request strictly aborted during form fill phase",
            )
            self.blocked_requests.append(record)
            logger.warning(
                "[ROUTE_GUARD_BLOCKED] Aborted %s request to %s during fill phase",
                method,
                req.url,
            )
            route.abort("blockedbyclient")

        self.page.route("**/*", _handle_route)
        self._installed = True
        logger.debug("FillRouteGuard successfully installed on page.")

    def uninstall(self) -> None:
        """Removes the route interception guard when exiting fill phase."""
        if self._installed:
            try:
                self.page.unroute("**/*")
            except Exception as e:
                logger.debug("Error while uninstalling route guard: %s", e)
            self._installed = False
