"""URL canonicalization and deduplication utilities."""

from typing import List, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def canonicalize_url(raw_url: str) -> str:
    """
    Normalizes a URL to a canonical format:
    - Strips whitespace
    - Lowercases scheme and netloc
    - Strips default ports (443 for https)
    - Normalizes empty paths to '/'
    - Sorts query parameters for consistent equality checking
    - Removes fragment
    """
    url = raw_url.strip()
    parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Remove default port
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = parsed.path or "/"

    # Normalize query string by sorting keys
    query_parts = parse_qsl(parsed.query, keep_blank_values=True)
    sorted_query = urlencode(sorted(query_parts))

    # Strip fragments
    return urlunparse((scheme, netloc, path, parsed.params, sorted_query, ""))


def deduplicate_urls(urls: List[str]) -> List[str]:
    """Deduplicates a list of URLs using canonical normalization while preserving order."""
    seen: Set[str] = set()
    result: List[str] = []

    for raw in urls:
        canonical = canonicalize_url(raw)
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)

    return result
