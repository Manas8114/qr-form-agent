"""Tests for URL safety gate, SSRF protection, redirect handling, and deduplication."""

import pytest
from qr_form_agent.safety.dedupe import canonicalize_url, deduplicate_urls
from qr_form_agent.safety.gate import run_safety_gate
from qr_form_agent.safety.url_gate import is_ip_allowed, validate_url


def test_is_ip_allowed_blocks_private_and_local():
    # Loopback
    assert is_ip_allowed("127.0.0.1")[0] is False
    assert is_ip_allowed("::1")[0] is False

    # RFC 1918 Private
    assert is_ip_allowed("10.0.0.1")[0] is False
    assert is_ip_allowed("172.16.0.1")[0] is False
    assert is_ip_allowed("192.168.1.254")[0] is False

    # Link-local & cloud metadata
    assert is_ip_allowed("169.254.169.254")[0] is False
    assert is_ip_allowed("169.254.0.1")[0] is False

    # Multicast & Broadcast
    assert is_ip_allowed("224.0.0.1")[0] is False
    assert is_ip_allowed("255.255.255.255")[0] is False

    # Public IP
    assert is_ip_allowed("8.8.8.8")[0] is True
    assert is_ip_allowed("1.1.1.1")[0] is True


def test_validate_url_rejects_non_https():
    res = validate_url("http://insecure.example.com/apply")
    assert res.is_safe is False
    assert "https" in res.error_reason.lower()

    res_ftp = validate_url("ftp://example.com/file")
    assert res_ftp.is_safe is False

    res_js = validate_url("javascript:alert(1)")
    assert res_js.is_safe is False


def test_validate_url_blocks_ssrf_targets():
    # Direct loopback IP
    res_loopback = validate_url("https://127.0.0.1/admin")
    assert res_loopback.is_safe is False
    assert "SSRF" in res_loopback.error_reason

    # Direct private IP
    res_private = validate_url("https://192.168.1.1/setup")
    assert res_private.is_safe is False
    assert "SSRF" in res_private.error_reason

    # Metadata host
    res_meta = validate_url("https://metadata.google.internal/computeMetadata/v1/")
    assert res_meta.is_safe is False
    assert "Disallowed metadata host" in res_meta.error_reason

    # Localhost host
    res_local = validate_url("https://localhost:8443/login")
    assert res_local.is_safe is False


def test_canonicalize_and_deduplicate_urls():
    raw_urls = [
        "https://careers.example.com:443/apply?b=2&a=1#section",
        "https://careers.example.com/apply?a=1&b=2",
        "https://CAREERS.EXAMPLE.COM/apply?b=2&a=1",
        "https://other.example.com/jobs",
    ]

    deduped = deduplicate_urls(raw_urls)
    assert len(deduped) == 2
    assert "https://careers.example.com/apply?a=1&b=2" in deduped
    assert "https://other.example.com/jobs/" in deduped or "https://other.example.com/jobs" in deduped


def test_run_safety_gate_flow():
    urls = [
        "https://127.0.0.1/evil",  # Unsafe SSRF
        "http://plain-http.com",   # Insecure scheme
        "https://example.com/careers?id=1",
        "https://example.com/careers?id=1",  # Duplicate
    ]

    # Rejection by operator
    report_rejected = run_safety_gate(
        urls,
        resolve_redirects=False,
        confirmation_callback=lambda u: False,
    )
    assert len(report_rejected.rejected_urls) >= 2
    assert report_rejected.user_confirmed is False
    assert report_rejected.approved_urls == []

    # Acceptance by operator
    report_accepted = run_safety_gate(
        urls,
        resolve_redirects=False,
        confirmation_callback=lambda u: True,
    )
    assert report_accepted.user_confirmed is True
    assert len(report_accepted.approved_urls) == 1
    assert "https://example.com/careers?id=1" in report_accepted.approved_urls[0]
