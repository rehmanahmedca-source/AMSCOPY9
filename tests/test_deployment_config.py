"""Tests for the central config.py deployment control center.

Covers: configuration validity, derived-endpoint construction, secret
separation, environment overrides (portability), the validator, and the
public /health endpoint.
"""
from __future__ import annotations

import importlib

import pytest


def test_default_config_is_valid():
    import config
    cfg = config.get_config()
    problems = config.validate_config(require_secrets=False)
    assert problems == [], problems
    assert cfg["github"]["repository"]
    assert cfg["github"]["branch"]
    assert cfg["pythonanywhere"]["username"]
    assert "." in cfg["pythonanywhere"]["domain"]


def test_endpoints_are_derived_from_config():
    import config
    cfg = config.get_config()
    gh, pa = cfg["github"], cfg["pythonanywhere"]
    assert gh["repo_url"] == f"https://github.com/{gh['owner']}/{gh['repository']}.git"
    assert pa["username"] in pa["reload_endpoint"]
    assert pa["domain"] in pa["reload_endpoint"]
    assert pa["reload_endpoint"].startswith(pa["api_base"])
    assert pa["health_url"] == f"{pa['app_base_url']}/health"
    assert pa["project_path"].startswith(f"/home/{pa['username']}")
    assert pa["wsgi_path"].endswith(".py")


def test_config_contains_no_literal_secret_values(monkeypatch):
    # Secret values must come from env vars; config only names them.
    import pathlib
    src = pathlib.Path("config.py").read_text()
    assert "PYTHONANYWHERE_API_TOKEN" in src  # the env-var name is present
    # A real token literal pattern must never appear
    assert "PakistanZindabad" not in src


def test_validator_requires_webhook_secret(monkeypatch):
    import config
    monkeypatch.delenv("AMS_WEBHOOK_TOKEN", raising=False)
    problems = config.validate_config(require_secrets=True)
    assert any("AMS_WEBHOOK_TOKEN" in p for p in problems)


def test_validator_catches_missing_username(monkeypatch):
    monkeypatch.setenv("AMS_PA_USERNAME", "")
    import config
    importlib.reload(config)
    try:
        problems = config.validate_config(require_secrets=False)
        assert any("username" in p.lower() for p in problems)
    finally:
        importlib.reload(config)


def test_portability_change_only_config(monkeypatch):
    """Changing owner/repo/username/domain recomputes the whole target."""
    monkeypatch.setenv("AMS_GITHUB_OWNER", "newowner")
    monkeypatch.setenv("AMS_GITHUB_REPOSITORY", "project-new")
    monkeypatch.setenv("AMS_GITHUB_BRANCH", "release")
    monkeypatch.setenv("AMS_PA_USERNAME", "newuser")
    monkeypatch.setenv("AMS_PA_DOMAIN", "newuser.pythonanywhere.com")
    import config
    importlib.reload(config)
    try:
        cfg = config.get_config()
        assert cfg["github"]["repo_url"] == "https://github.com/newowner/project-new.git"
        assert cfg["github"]["branch"] == "release"
        assert cfg["pythonanywhere"]["username"] == "newuser"
        assert cfg["pythonanywhere"]["project_path"] == "/home/newuser/project-new"
        assert "newuser.pythonanywhere.com" in cfg["pythonanywhere"]["reload_endpoint"]
        assert cfg["pythonanywhere"]["health_url"].startswith(
            "https://newuser.pythonanywhere.com"
        )
        assert config.validate_config(require_secrets=False) == []
    finally:
        importlib.reload(config)


def test_health_endpoint_is_public_and_healthy(app, client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["database"] == "ok"


def test_webhook_get_is_online_but_post_requires_token(app, client):
    resp = client.get("/git-auto-pull")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "online"
    # POST without a configured token is rejected
    resp = client.post(
        "/git-auto-pull",
        json={"ref": "refs/heads/main"},
        headers={"X-GitHub-Event": "push"},
    )
    assert resp.status_code in (403, 503)


def test_deployer_dry_run_needs_secret(app, monkeypatch):
    monkeypatch.delenv("AMS_WEBHOOK_TOKEN", raising=False)
    from deploy import deployer
    res = deployer.deploy(dry_run=True)
    assert res["ok"] is False
