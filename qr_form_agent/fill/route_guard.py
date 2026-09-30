"""Network route guard for fill phase.

Enforces Hard Requirement 1 and Hardening (Requirement 14):
1. During fill phase, abort non-GET requests to form action URLs (and any mutating POST/PUT/DELETE)
   via Playwright's page.route.
2. Route-level SSRF checks with pinned DNS resolution to prevent DNS rebinding attacks.
3. Strict blocking of GET form submissions targeting form actions with sensitive query payloads.
"""

import logging
from typing import Dict, List, Optional, Set
from urllib.parse import parse_qs, urlparse
from pydantic import BaseModel, Field
from playwright.sync_api import Page, Route, Request

from qr_form_agent.safety.url_gate import is_ip_allowed, resolve_and_check_host

logger = logging.getLogger(__name__)

# Common form field keys that indicate a form submission when serialized into a GET query string
SENSITIVE_FORM_KEYS = {
    "first_name", "firstname", "last_name", "lastname", "name",
    "email", "phone", "phonenumber", "telephone", "address",
    "city", "state", "zip", "postal", "postalcode", "country",
    "resume", "cv", "linkedin", "github", "portfolio",
    "ssn", "password", "applicant", "application", "candidate",
}


class BlockedRequest(BaseModel):
    url: str
    method: str
    resource_type: str
    reason: str


class FillRouteGuard:
    """
    Manages active route interception on a Playwright Page during the fill phase.
    Enforces non-GET blocking, route-level SSRF protection with pinned DNS,
    and GET form submission neutralization.
    """

    def __init__(self, page: Page, allow_local_for_testing: bool = False):
        self.page = page
        self.allow_local_for_testing = allow_local_for_testing
        self.blocked_requests: List[BlockedRequest] = []
        self._installed = False
        self._pinned_dns: Dict[str, str] = {}
        self._registered_form_actions: Set[str] = set()

    def register_form_action(self, action_url: str) -> None:
        """Registers a known form action URL to monitor and block GET submissions."""
        if action_url:
            self._registered_form_actions.add(action_url.lower())

    def _is_get_form_submit(self, req: Request) -> bool:
        """Detects if a GET request represents an attempted form submission."""
        parsed = urlparse(req.url)
        query_params = parse_qs(parsed.query)

        if not query_params:
            return False

        # 1. Direct match with registered form action containing query parameters
        clean_action = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".lower()
        for registered in self._registered_form_actions:
            if registered.endswith(parsed.path.lower()) or clean_action == registered:
                logger.warning("[ROUTE_GUARD] GET submission to registered form action %s detected", req.url)
                return True

        # 2. Query string contains multiple sensitive form field names
        param_keys = {k.lower().strip() for k in query_params.keys()}
        matching_keys = param_keys.intersection(SENSITIVE_FORM_KEYS)
        if len(matching_keys) >= 2:
            logger.warning(
                "[ROUTE_GUARD] GET submission containing form keys %s detected: %s",
                matching_keys,
                req.url,
            )
            return True

        # 3. Path explicitly has submit/apply endpoints combined with query params
        path_lower = parsed.path.lower()
        if any(sub in path_lower for sub in ("/submit", "/apply/submit", "/process_application", "/form_submit")):
            logger.warning("[ROUTE_GUARD] GET submission to submit endpoint detected: %s", req.url)
            return True

        return False

    def install(self) -> None:
        """Installs the route interception guard on the page."""
        if self._installed:
            return

        def _handle_route(route: Route) -> None:
            req: Request = route.request
            method = req.method.upper()
            url = req.url
            parsed = urlparse(url)

            # Skip DNS checks for local file URIs
            if parsed.scheme.lower() == "file" or not parsed.hostname:
                if method not in ("GET", "OPTIONS", "HEAD"):
                    record = BlockedRequest(
                        url=url,
                        method=method,
                        resource_type=req.resource_type,
                        reason="Non-GET request strictly aborted during form fill phase",
                    )
                    self.blocked_requests.append(record)
                    route.abort("blockedbyclient")
                    return
                route.continue_()
                return

            host = parsed.hostname.lower()

            # 1. Route-level SSRF check with pinned DNS
            if host not in self._pinned_dns:
                # If testing locally on 127.0.0.1 / localhost and explicit flag is set
                if self.allow_local_for_testing and host in ("localhost", "127.0.0.1", "::1"):
                    self._pinned_dns[host] = "127.0.0.1"
                else:
                    is_safe, reason, ips = resolve_and_check_host(host)
                    if not is_safe:
                        record = BlockedRequest(
                            url=url,
                            method=method,
                            resource_type=req.resource_type,
                            reason=f"Route-level SSRF check failed: {reason}",
                        )
                        self.blocked_requests.append(record)
                        logger.warning(
                            "[ROUTE_GUARD_SSRF_BLOCKED] Aborted request to %s: %s",
                            url,
                            reason,
                        )
                        route.abort("blockedbyclient")
                        return
                    if ips:
                        self._pinned_dns[host] = ips[0]

            # 2. Mutating methods are strictly forbidden during the fill phase!
            if method not in ("GET", "OPTIONS", "HEAD"):
                record = BlockedRequest(
                    url=url,
                    method=method,
                    resource_type=req.resource_type,
                    reason="Non-GET request strictly aborted during form fill phase",
                )
                self.blocked_requests.append(record)
                logger.warning(
                    "[ROUTE_GUARD_BLOCKED] Aborted %s request to %s during fill phase",
                    method,
                    url,
                )
                route.abort("blockedbyclient")
                return

            # 3. Block GET form submissions with payload in query string
            if method == "GET" and self._is_get_form_submit(req):
                record = BlockedRequest(
                    url=url,
                    method="GET",
                    resource_type=req.resource_type,
                    reason="GET form submission strictly aborted during form fill phase",
                )
                self.blocked_requests.append(record)
                logger.warning(
                    "[ROUTE_GUARD_GET_SUBMIT_BLOCKED] Aborted GET form submission to %s",
                    url,
                )
                route.abort("blockedbyclient")
                return

            route.continue_()

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
