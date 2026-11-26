from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.server import (
    MAX_REQUEST_BYTES,
    MAX_WEBHOOK_BYTES,
    _SlidingWindowRateLimiter,
    create_app,
)
from pmcursor.indexer import index_repository
from pmcursor.mcp_server import RepoIndexCache
from pmcursor.models import RepoMap


def _create_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass User(BaseModel):\n    id: int\n",
        encoding="utf-8",
    )
    return repo


def test_request_id_and_process_time_headers_and_structured_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app()
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="api.server"):
        generated_resp = client.get("/health")
        propagated_resp = client.get(
            "/health",
            headers={
                "X-Request-ID": "req-enterprise-123",
                "Authorization": "Bearer secret-token",
            },
        )

    assert generated_resp.status_code == 200
    gen_id = generated_resp.headers.get("X-Request-ID")
    assert gen_id is not None
    uuid.UUID(gen_id)
    gen_time = generated_resp.headers.get("X-Process-Time-Ms")
    assert gen_time is not None
    assert re.match(r"^\d+\.\d{2}$", gen_time)

    assert propagated_resp.status_code == 200
    assert propagated_resp.headers.get("X-Request-ID") == "req-enterprise-123"
    prop_time = propagated_resp.headers.get("X-Process-Time-Ms")
    assert prop_time is not None
    assert re.match(r"^\d+\.\d{2}$", prop_time)

    records = [json.loads(r.message) for r in caplog.records if r.name == "api.server"]
    assert len(records) >= 2
    last_log = records[-1]
    assert last_log["method"] == "GET"
    assert last_log["path"] == "/health"
    assert last_log["status_code"] == 200
    assert isinstance(last_log["duration_ms"], float)
    assert last_log["request_id"] == "req-enterprise-123"
    assert "secret-token" not in json.dumps(last_log)


def test_readyz_and_repo_index_cache_avoids_redundant_indexing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _create_sample_repo(tmp_path)
    cache = RepoIndexCache()
    calls: list[Path] = []

    def counting_index_repository(repo_root: Path) -> RepoMap:
        calls.append(repo_root)
        return index_repository(repo_root)

    monkeypatch.setattr("pmcursor.mcp_server.index_repository", counting_index_repository)

    app = create_app(repo_cache=cache)
    client = TestClient(app)

    ready_before = client.get("/readyz")
    assert ready_before.status_code == 200
    assert ready_before.json() == {"status": "ready", "cached_repos": 0}
    assert cache.size == 0

    payload: dict[str, Any] = {
        "repo_root": str(repo),
        "prd_markdown": "# PRD\n\n- User model\n",
        "prd_path": "PRD.md",
    }
    first_audit = client.post("/v1/drift/audit", json=payload)
    assert first_audit.status_code == 200
    assert len(calls) == 1
    assert cache.size == 1

    ready_after = client.get("/readyz")
    assert ready_after.status_code == 200
    assert ready_after.json() == {"status": "ready", "cached_repos": 1}

    second_audit = client.post("/v1/drift/audit", json=payload)
    assert second_audit.status_code == 200
    assert len(calls) == 1

    cache.clear()
    assert cache.size == 0
    ready_cleared = client.get("/readyz")
    assert ready_cleared.status_code == 200
    assert ready_cleared.json() == {"status": "ready", "cached_repos": 0}


@pytest.mark.parametrize(
    "endpoint",
    [
        "/v1/webhooks/github",
        "/v1/webhooks/linear",
        "/v1/webhooks/jira",
    ],
)
def test_oversized_webhook_payload_returns_413(endpoint: str) -> None:
    app = create_app(
        webhook_secret="gh-secret",
        linear_webhook_secret="lin-secret",
        jira_webhook_secret="jira-secret",
    )
    client = TestClient(app)

    oversized_body = b"x" * (MAX_WEBHOOK_BYTES + 1)
    resp = client.post(
        endpoint,
        content=oversized_body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"] == "Request payload exceeds 2MB limit"

    header_oversized_resp = client.post(
        endpoint,
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(MAX_WEBHOOK_BYTES + 1),
        },
    )
    assert header_oversized_resp.status_code == 413
    assert header_oversized_resp.json()["detail"] == "Request payload exceeds 2MB limit"


def test_oversized_content_length_returns_413_on_drift_audit(tmp_path: Path) -> None:
    _create_sample_repo(tmp_path)
    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/v1/drift/audit",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(MAX_REQUEST_BYTES + 1),
            "X-Request-ID": "req-oversized-1",
        },
    )
    assert resp.status_code == 413
    assert resp.json()["detail"] == "Request payload exceeds 2MB limit"
    assert resp.headers.get("X-Request-ID") == "req-oversized-1"
    assert resp.headers.get("X-Process-Time-Ms") is not None

    neg_resp = client.post(
        "/v1/drift/audit",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": "-1",
        },
    )
    assert neg_resp.status_code == 413
    assert neg_resp.json()["detail"] == "Request payload exceeds 2MB limit"


def test_prometheus_metrics_endpoint(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    cache = RepoIndexCache()
    app = create_app(repo_cache=cache)
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert (
        client.post(
            "/v1/drift/audit",
            json={
                "repo_root": str(repo),
                "prd_markdown": "# PRD\n\n- User model\n",
                "prd_path": "PRD.md",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/drift/audit",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(MAX_REQUEST_BYTES + 1),
            },
        ).status_code
        == 413
    )

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    assert metrics_resp.headers["content-type"].startswith("text/plain")
    body = metrics_resp.text
    assert "pmcursor_http_requests_total 3" in body
    assert "pmcursor_http_errors_total 1" in body
    assert "pmcursor_repo_cache_entries 1" in body
    assert "pmcursor_repo_cache_hits_total" in body
    assert "pmcursor_repo_cache_misses_total" in body


def test_security_headers_present_on_responses() -> None:
    app = create_app()
    client = TestClient(app)

    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert health_resp.headers.get("X-Frame-Options") == "DENY"
    assert health_resp.headers.get("Referrer-Policy") == "no-referrer"

    error_resp = client.post(
        "/v1/drift/audit",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(MAX_REQUEST_BYTES + 1),
        },
    )
    assert error_resp.status_code == 413
    assert error_resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert error_resp.headers.get("X-Frame-Options") == "DENY"
    assert error_resp.headers.get("Referrer-Policy") == "no-referrer"


def test_sliding_window_rate_limit_and_probe_exemptions(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    app = create_app(rate_limit_per_minute=2)
    client = TestClient(app)

    payload: dict[str, Any] = {
        "repo_root": str(repo),
        "prd_markdown": "# PRD\n\n- User model\n",
        "prd_path": "PRD.md",
    }
    first = client.post("/v1/drift/audit", json=payload)
    second = client.post("/v1/drift/audit", json=payload)
    third = client.post("/v1/drift/audit", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json() == {"detail": "Rate limit exceeded"}
    assert third.headers.get("Retry-After") == "60"
    assert third.headers.get("X-Request-ID") is not None
    assert third.headers.get("X-Process-Time-Ms") is not None
    assert third.headers.get("X-Content-Type-Options") == "nosniff"

    for _ in range(5):
        assert client.get("/health").status_code == 200
        assert client.get("/readyz").status_code == 200


def test_github_and_linear_webhook_delivery_deduplication(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    gh_secret = "gh-secret"
    lin_secret = "lin-secret"
    app = create_app(
        webhook_secret=gh_secret,
        linear_webhook_secret=lin_secret,
        allowed_workspace_root=tmp_path,
    )
    client = TestClient(app)

    gh_body = json.dumps({"zen": "Keep it logically awesome.", "hook_id": 99}).encode(
        "utf-8"
    )
    gh_sig = (
        "sha256="
        + hmac.new(gh_secret.encode("utf-8"), gh_body, hashlib.sha256).hexdigest()
    )
    gh_headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": gh_sig,
        "X-GitHub-Delivery": "gh-deliv-1",
    }
    gh_first = client.post("/v1/webhooks/github", content=gh_body, headers=gh_headers)
    gh_second = client.post("/v1/webhooks/github", content=gh_body, headers=gh_headers)
    assert gh_first.status_code == 200
    assert gh_first.json() == {"status": "pong", "hook_id": 99}
    assert gh_second.status_code == 200
    assert gh_second.json() == {"status": "duplicate", "delivery_id": "gh-deliv-1"}

    lin_body = json.dumps(
        {
            "type": "Comment",
            "repo_root": str(repo),
            "data": {"id": "1"},
        }
    ).encode("utf-8")
    lin_sig = hmac.new(lin_secret.encode("utf-8"), lin_body, hashlib.sha256).hexdigest()
    lin_headers = {
        "Content-Type": "application/json",
        "Linear-Signature": lin_sig,
        "Linear-Delivery": "lin-deliv-1",
    }
    lin_first = client.post("/v1/webhooks/linear", content=lin_body, headers=lin_headers)
    lin_second = client.post("/v1/webhooks/linear", content=lin_body, headers=lin_headers)
    assert lin_first.status_code == 200
    assert lin_first.json() == {"status": "ignored", "event_type": "Comment"}
    assert lin_second.status_code == 200
    assert lin_second.json() == {"status": "duplicate", "delivery_id": "lin-deliv-1"}


def test_cache_clear_endpoint_requires_auth_and_clears_cache(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    cache = RepoIndexCache()
    app = create_app(api_token="top-secret", repo_cache=cache)
    client = TestClient(app)
    auth_headers = {"Authorization": "Bearer top-secret"}

    audit_resp = client.post(
        "/v1/drift/audit",
        json={
            "repo_root": str(repo),
            "prd_markdown": "# PRD\n\n- User model\n",
            "prd_path": "PRD.md",
        },
        headers=auth_headers,
    )
    assert audit_resp.status_code == 200
    assert client.get("/readyz").json() == {"status": "ready", "cached_repos": 1}

    unauth_clear = client.post("/v1/cache/clear")
    assert unauth_clear.status_code == 401
    assert cache.size == 1

    clear_resp = client.post("/v1/cache/clear", headers=auth_headers)
    assert clear_resp.status_code == 200
    clear_data = clear_resp.json()
    assert clear_data["status"] == "cleared"
    assert clear_data["cleared_entries"] >= 1
    assert client.get("/readyz").json() == {"status": "ready", "cached_repos": 0}


def test_trust_proxy_rate_limits_by_x_forwarded_for(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    app = create_app(rate_limit_per_minute=1, trust_proxy=True)
    client = TestClient(app)

    payload: dict[str, Any] = {
        "repo_root": str(repo),
        "prd_markdown": "# PRD\n\n- User model\n",
        "prd_path": "PRD.md",
    }
    ip1_headers = {"X-Forwarded-For": "203.0.113.10, 10.0.0.1"}
    ip2_headers = {"X-Forwarded-For": "203.0.113.20"}

    assert client.post("/v1/drift/audit", json=payload, headers=ip1_headers).status_code == 200
    assert client.post("/v1/drift/audit", json=payload, headers=ip1_headers).status_code == 429
    assert client.post("/v1/drift/audit", json=payload, headers=ip2_headers).status_code == 200
    assert client.post("/v1/drift/audit", json=payload, headers=ip2_headers).status_code == 429


def test_jira_webhook_delivery_deduplication(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path)
    jira_secret = "jira-secret"
    app = create_app(
        jira_webhook_secret=jira_secret,
        allowed_workspace_root=tmp_path,
    )
    client = TestClient(app)

    jira_body = json.dumps(
        {
            "webhookEvent": "jira:comment_created",
            "repo_root": str(repo),
            "issue": {"key": "PROJ-42", "fields": {"summary": "Test", "description": "Desc"}},
        }
    ).encode("utf-8")
    jira_sig = (
        "sha256="
        + hmac.new(jira_secret.encode("utf-8"), jira_body, hashlib.sha256).hexdigest()
    )
    jira_headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature": jira_sig,
        "X-Atlassian-Webhook-Identifier": "jira-deliv-1",
    }
    first = client.post("/v1/webhooks/jira", content=jira_body, headers=jira_headers)
    second = client.post("/v1/webhooks/jira", content=jira_body, headers=jira_headers)
    assert first.status_code == 200
    assert first.json()["ticket_id"] == "PROJ-42"
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate", "delivery_id": "jira-deliv-1"}


def test_cors_origins_allowlist_and_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PMCURSOR_CORS_ORIGINS", raising=False)
    default_client = TestClient(create_app())
    default_resp = default_client.get(
        "/health",
        headers={"Origin": "https://app.example.com"},
    )
    assert default_resp.status_code == 200
    assert "access-control-allow-origin" not in default_resp.headers

    allowlist_client = TestClient(
        create_app(cors_origins=["https://app.example.com"])
    )
    allowed_resp = allowlist_client.get(
        "/health",
        headers={"Origin": "https://app.example.com"},
    )
    assert allowed_resp.status_code == 200
    assert allowed_resp.headers.get("access-control-allow-origin") == "https://app.example.com"

    disallowed_resp = allowlist_client.get(
        "/health",
        headers={"Origin": "https://evil.example.com"},
    )
    assert disallowed_resp.status_code == 200
    assert "access-control-allow-origin" not in disallowed_resp.headers

    preflight_resp = allowlist_client.options(
        "/v1/drift/audit",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert preflight_resp.status_code == 200
    assert preflight_resp.headers.get("access-control-allow-origin") == "https://app.example.com"

    monkeypatch.setenv(
        "PMCURSOR_CORS_ORIGINS",
        " https://env.example.com , , https://admin.example.com ",
    )
    env_client = TestClient(create_app())
    env_allowed = env_client.get(
        "/health",
        headers={"Origin": "https://admin.example.com"},
    )
    assert env_allowed.status_code == 200
    assert env_allowed.headers.get("access-control-allow-origin") == "https://admin.example.com"


def test_sliding_window_rate_limiter_lru_eviction() -> None:
    with pytest.raises(ValueError, match="max_clients"):
        _SlidingWindowRateLimiter(max_requests=1, max_clients=0)

    limiter = _SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0, max_clients=2)
    assert limiter.allow("c1") is True
    assert limiter.allow("c1") is False
    assert limiter.allow("c2") is True
    # Touch c1 so c2 becomes the least recently used client bucket.
    assert limiter.allow("c1") is False
    # Adding c3 must evict c2 while keeping c1 rate-limited.
    assert limiter.allow("c3") is True
    assert limiter.allow("c1") is False
    assert limiter.allow("c2") is True


def test_publish_endpoint_auth_validation_and_dry_run() -> None:
    app = create_app(api_token="publish-secret")
    client = TestClient(app)
    headers = {"Authorization": "Bearer publish-secret"}

    unauth_resp = client.post(
        "/v1/publish",
        json={"provider": "github", "target": "acme/repo#12", "body": "LGTM"},
    )
    assert unauth_resp.status_code == 401

    invalid_gh = client.post(
        "/v1/publish",
        json={"provider": "github", "target": "acme/repo", "body": "LGTM"},
        headers=headers,
    )
    assert invalid_gh.status_code == 422

    missing_jira_url = client.post(
        "/v1/publish",
        json={"provider": "jira", "target": "PROJ-12", "body": "Updated"},
        headers=headers,
    )
    assert missing_jira_url.status_code == 422

    gh_ok = client.post(
        "/v1/publish",
        json={"provider": "github", "target": "acme/repo#12", "body": "LGTM", "dry_run": True},
        headers=headers,
    )
    assert gh_ok.status_code == 200
    gh_data = gh_ok.json()
    assert gh_data["provider"] == "github"
    assert gh_data["target_id"] == "acme/repo#12"
    assert gh_data["dry_run"] is True
    assert gh_data["status_code"] == 0

    linear_ok = client.post(
        "/v1/publish",
        json={"provider": "linear", "target": "LIN-99", "body": "Synced", "dry_run": True},
        headers=headers,
    )
    assert linear_ok.status_code == 200
    linear_data = linear_ok.json()
    assert linear_data["provider"] == "linear"
    assert linear_data["target_id"] == "LIN-99"
    assert linear_data["dry_run"] is True

    jira_ok = client.post(
        "/v1/publish",
        json={
            "provider": "jira",
            "target": "PROJ-12",
            "body": "Synced",
            "jira_base_url": "https://jira.example.com",
            "dry_run": True,
        },
        headers=headers,
    )
    assert jira_ok.status_code == 200
    jira_data = jira_ok.json()
    assert jira_data["provider"] == "jira"
    assert jira_data["target_id"] == "PROJ-12"
    assert jira_data["dry_run"] is True
