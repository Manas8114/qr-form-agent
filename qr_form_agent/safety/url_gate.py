"""URL safety gate with HTTPS enforcement, SSRF prevention, and redirect verification."""

import ipaddress
import logging
import socket
from typing import List, Optional, Tuple
from urllib.parse import urlparse
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Disallowed metadata domains often targeted in SSRF attacks
DISALLOWED_METADATA_HOSTS = {
    "metadata.google.internal",
    "instance-data",
    "169.254.169.254",
    "metadata",
}


class ValidationResult(BaseModel):
    is_safe: bool = Field(description="True if URL passed all safety criteria")
    final_url: Optional[str] = Field(default=None, description="Final resolved destination URL")
    error_reason: Optional[str] = Field(default=None, description="Explanation if rejected")
    hops: List[str] = Field(default_factory=list, description="Chain of URLs traversed during redirects")
    resolved_ips: List[str] = Field(default_factory=list, description="Resolved IP addresses")


def is_ip_allowed(ip_str: str) -> Tuple[bool, Optional[str]]:
    """
    Validates that an IP address is not private, loopback, link-local, multicast, or reserved.
    Fails closed on any invalid IP format.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False, f"Invalid IP format: {ip_str}"

    if ip.is_private:
        return False, f"Private IP address disallowed: {ip_str}"
    if ip.is_loopback:
        return False, f"Loopback address disallowed: {ip_str}"
    if ip.is_link_local:
        return False, f"Link-local address disallowed: {ip_str}"
    if ip.is_multicast:
        return False, f"Multicast address disallowed: {ip_str}"
    if ip.is_reserved:
        return False, f"Reserved address disallowed: {ip_str}"
    if ip.is_unspecified:
        return False, f"Unspecified address disallowed: {ip_str}"

    # Explicit check for AWS/GCP/Azure link-local metadata address 169.254.169.254
    if str(ip) == "169.254.169.254":
        return False, "Cloud metadata IP disallowed: 169.254.169.254"

    return True, None


def resolve_and_check_host(host: str) -> Tuple[bool, Optional[str], List[str]]:
    """
    Resolves a hostname via DNS and verifies that all resolved IP addresses pass safety checks.
    """
    if not host:
        return False, "Empty host", []

    clean_host = host.lower().strip("[]")
    if clean_host in DISALLOWED_METADATA_HOSTS:
        return False, f"Disallowed metadata host: {clean_host}", []

    try:
        # Resolve both IPv4 and IPv6
        addr_info = socket.getaddrinfo(clean_host, None)
    except socket.gaierror as e:
        return False, f"DNS resolution failed for {clean_host}: {e}", []

    resolved_ips: List[str] = []
    for entry in addr_info:
        ip_str = entry[4][0]
        if ip_str not in resolved_ips:
            resolved_ips.append(ip_str)

    if not resolved_ips:
        return False, f"No IP addresses resolved for host {clean_host}", []

    for ip_str in resolved_ips:
        allowed, reason = is_ip_allowed(ip_str)
        if not allowed:
            return False, reason, resolved_ips

    return True, None, resolved_ips


def validate_url(
    url: str,
    resolve_redirects: bool = True,
    max_redirects: int = 5,
) -> ValidationResult:
    """
    Validates a URL against strict security criteria:
      1. HTTPS scheme only (http, file, javascript, etc. strictly forbidden)
      2. DNS resolution verifies public IP (SSRF guard against private/link-local/loopback)
      3. Hop-by-hop redirect verification (ensures intermediate and destination hops are safe)
    """
    current_url = url.strip()
    hops: List[str] = [current_url]
    all_resolved_ips: List[str] = []

    # Step 1: Scheme check
    parsed = urlparse(current_url)
    if parsed.scheme.lower() != "https":
        return ValidationResult(
            is_safe=False,
            final_url=None,
            error_reason=f"Only https:// URLs are permitted. Given scheme: {parsed.scheme}",
            hops=hops,
        )

    # Step 2: Host SSRF check
    host = parsed.hostname
    if not host:
        return ValidationResult(
            is_safe=False,
            final_url=None,
            error_reason="URL does not contain a valid hostname.",
            hops=hops,
        )

    allowed, reason, ips = resolve_and_check_host(host)
    all_resolved_ips.extend(ips)
    if not allowed:
        return ValidationResult(
            is_safe=False,
            final_url=None,
            error_reason=f"SSRF safety check failed: {reason}",
            hops=hops,
            resolved_ips=all_resolved_ips,
        )

    if not resolve_redirects:
        return ValidationResult(
            is_safe=True,
            final_url=current_url,
            hops=hops,
            resolved_ips=all_resolved_ips,
        )

    # Step 3: Follow redirects safely hop-by-hop
    redirect_count = 0
    try:
        with httpx.Client(follow_redirects=False, timeout=5.0, verify=True) as client:
            while redirect_count < max_redirects:
                try:
                    response = client.head(current_url)
                except httpx.RequestError as e:
                    # Some servers block HEAD, fallback to GET with streaming
                    try:
                        response = client.get(current_url)
                    except httpx.RequestError as get_err:
                        logger.warning("Network connection failed during check of %s: %s", current_url, get_err)
                        # If offline or domain unreachable, we allow if host resolved safely
                        break

                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        break

                    # Construct full absolute URL for next hop
                    next_url = str(response.url.join(location))
                    redirect_count += 1
                    hops.append(next_url)

                    # Re-verify HTTPS & host safety on next hop!
                    next_parsed = urlparse(next_url)
                    if next_parsed.scheme.lower() != "https":
                        return ValidationResult(
                            is_safe=False,
                            final_url=None,
                            error_reason=f"Redirect to non-HTTPS scheme forbidden: {next_url}",
                            hops=hops,
                            resolved_ips=all_resolved_ips,
                        )

                    next_host = next_parsed.hostname or ""
                    next_allowed, next_reason, next_ips = resolve_and_check_host(next_host)
                    all_resolved_ips.extend(next_ips)
                    if not next_allowed:
                        return ValidationResult(
                            is_safe=False,
                            final_url=None,
                            error_reason=f"Redirect hop SSRF safety check failed: {next_reason}",
                            hops=hops,
                            resolved_ips=all_resolved_ips,
                        )

                    current_url = next_url
                else:
                    break

        return ValidationResult(
            is_safe=True,
            final_url=current_url,
            hops=hops,
            resolved_ips=list(set(all_resolved_ips)),
        )

    except Exception as e:
        logger.error("Unexpected error validating URL %s: %s", url, e)
        return ValidationResult(
            is_safe=False,
            final_url=None,
            error_reason=f"Validation failed with exception: {e}",
            hops=hops,
        )
