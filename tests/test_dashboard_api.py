"""Tests for Frontend Control Center & Dashboard API endpoints."""

import pytest
from fastapi.testclient import TestClient

from qr_form_agent.core.kill_switch import deactivate_kill_switch, is_kill_switch_active
from qr_form_agent.review.app import app


@pytest.fixture
def client():
    deactivate_kill_switch()
    return TestClient(app)


def test_index_page_loads(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "QR Form Agent" in res.text
    assert "Frontend Control Center" in res.text


def test_static_assets_served(client):
    res_css = client.get("/static/style.css")
    assert res_css.status_code == 200
    assert "--primary-gradient" in res_css.text

    res_js = client.get("/static/app.js")
    assert res_js.status_code == 200
    assert "setupNavigationTabs" in res_js.text


def test_get_system_stats(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_jobs" in data
    assert "counts" in data
    assert "kill_switch_active" in data
    assert data["kill_switch_active"] is False


def test_kill_switch_toggle_api(client):
    # Activate
    res = client.post("/api/kill-switch/toggle", data={"activate": "true", "reason": "Test activation"})
    assert res.status_code == 200
    assert res.json()["kill_switch_active"] is True
    assert is_kill_switch_active() is True

    # Deactivate
    res2 = client.post("/api/kill-switch/toggle", data={"activate": "false", "reason": "Test deactivation"})
    assert res2.status_code == 200
    assert res2.json()["kill_switch_active"] is False
    assert is_kill_switch_active() is False


def test_profile_api_get_and_post(client):
    payload = {
        "full_name": "Taylor Morgan",
        "first_name": "Taylor",
        "last_name": "Morgan",
        "email": "taylor.morgan@domain.com",
        "phone": "+1-555-987-6543",
        "skills": ["Python", "FastAPI", "Playwright"],
    }
    res_post = client.post("/api/profile", json=payload)
    assert res_post.status_code == 200
    assert res_post.json()["success"] is True

    res_get = client.get("/api/profile")
    assert res_get.status_code == 200
    data = res_get.json()
    assert data["exists"] is True
    assert data["profile"]["full_name"] == "Taylor Morgan"
    assert data["profile"]["email"] == "taylor.morgan@domain.com"


def test_audit_logs_api(client):
    res = client.get("/api/audit-logs")
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    assert isinstance(data["logs"], list)
