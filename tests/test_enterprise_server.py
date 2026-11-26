from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.server import MAX_WEBHOOK_BYTES, create_app
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
    assert resp.json()["detail"] == "Webhook payload exceeds 2MB limit"

    header_oversized_resp = client.post(
        endpoint,
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(MAX_WEBHOOK_BYTES + 1),
        },
    )
    assert header_oversized_resp.status_code == 413
