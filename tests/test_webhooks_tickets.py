from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import (
    parse_jira_webhook_issue,
    parse_linear_webhook_issue,
    verify_jira_signature,
    verify_linear_signature,
)
from api.server import create_app
from pmcursor.tickets import TicketSyncReport


def _create_sample_repo(base: Path) -> Path:
    app_dir = base / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "models.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class Order(BaseModel):\n"
        "    order_id: str\n"
        "    total_cents: int\n",
        encoding="utf-8",
    )
    return base


def _sample_prd() -> str:
    return (
        "# Order PRD\n\n"
        "Backed by `app/models.py:3`.\n\n"
        "## Contracts\n"
        "- `Order.order_id: str`\n"
        "- `Order.total_cents: int`\n\n"
        "## Acceptance Criteria\n"
        "1. `protects=order schema; fails_when=missing field; no_claim=payment gateway`\n\n"
        "## Out of Scope\n"
        "- Refunds.\n\n"
        "## Rollback Plan\n"
        "- Revert schema change.\n"
    )


def _sign_linear(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _sign_jira(body: bytes, secret: str) -> str:
    return f"sha256={_sign_linear(body, secret)}"


def test_signature_helpers_and_parsers() -> None:
    body = b'{"hello":"world"}'
    assert verify_linear_signature(body, _sign_linear(body, "sec"), "sec")
    assert not verify_linear_signature(body, "bad", "sec")
    assert not verify_linear_signature(body, "", "sec")
    assert not verify_linear_signature(body, _sign_linear(body, "sec"), "")

    assert verify_jira_signature(body, _sign_jira(body, "sec"), "sec")
    assert not verify_jira_signature(body, _sign_linear(body, "sec"), "sec")

    assert parse_linear_webhook_issue(
        {
            "type": "Issue",
            "data": {"identifier": "ENG-10", "title": "Fix bug", "description": "Details"},
        }
    ) == ("ENG-10", "Fix bug", "Details")
    assert parse_linear_webhook_issue({"type": "Comment", "data": {"id": "1"}}) is None

    assert parse_jira_webhook_issue(
        {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": "PROJ-7",
                "fields": {"summary": "Add field", "description": {"type": "doc"}},
            },
        }
    ) == ("PROJ-7", "Add field", "")
    assert parse_jira_webhook_issue({"webhookEvent": "sprint_started"}) is None


def test_linear_webhook_invalid_or_missing_signature_returns_401(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(linear_webhook_secret="linear-secret", allowed_workspace_root=tmp_path)
    client = TestClient(app)
    body = json.dumps(
        {
            "type": "Issue",
            "repo_root": str(repo_root),
            "data": {"identifier": "ENG-42", "title": "Order schema", "description": _sample_prd()},
        }
    ).encode("utf-8")

    missing = client.post(
        "/v1/webhooks/linear",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    invalid = client.post(
        "/v1/webhooks/linear",
        content=body,
        headers={"Content-Type": "application/json", "Linear-Signature": "deadbeef"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_linear_webhook_valid_issue_returns_200(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    secret = "linear-secret"
    app = create_app(linear_webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)
    body = json.dumps(
        {
            "type": "Issue",
            "repo_root": str(repo_root),
            "data": {
                "identifier": "ENG-42",
                "title": "Order schema",
                "description": _sample_prd(),
            },
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/linear",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Linear-Signature": _sign_linear(body, secret),
        },
    )

    assert response.status_code == 200
    report = TicketSyncReport.model_validate(response.json())
    assert report.provider == "linear"
    assert report.ticket_id == "ENG-42"
    assert report.drift_report.status == "DONE"


def test_linear_webhook_non_issue_event_is_ignored(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    secret = "linear-secret"
    app = create_app(linear_webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)
    body = json.dumps(
        {
            "type": "Comment",
            "repo_root": str(repo_root),
            "data": {"id": "comment-1", "body": "Looks good"},
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/linear",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Linear-Signature": _sign_linear(body, secret),
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "event_type": "Comment"}


def test_linear_webhook_escaping_repo_root_returns_403(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _create_sample_repo(tmp_path / "outside")
    secret = "linear-secret"
    app = create_app(linear_webhook_secret=secret, allowed_workspace_root=workspace)
    client = TestClient(app)
    body = json.dumps(
        {
            "type": "Issue",
            "repo_root": str(outside),
            "data": {"identifier": "ENG-99", "title": "Escape", "description": _sample_prd()},
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/linear",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Linear-Signature": _sign_linear(body, secret),
        },
    )

    assert response.status_code == 403


def test_jira_webhook_valid_hmac_returns_200(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    secret = "jira-secret"
    app = create_app(jira_webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)
    payload: dict[str, Any] = {
        "webhookEvent": "jira:issue_created",
        "repo_root": str(repo_root),
        "issue": {
            "key": "PROJ-42",
            "fields": {
                "summary": "Order schema",
                "description": _sample_prd(),
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/v1/webhooks/jira",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature": _sign_jira(body, secret),
        },
    )

    assert response.status_code == 200
    report = TicketSyncReport.model_validate(response.json())
    assert report.provider == "jira"
    assert report.ticket_id == "PROJ-42"
    assert report.drift_report.status == "DONE"


def test_jira_webhook_invalid_signature_returns_401(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(jira_webhook_secret="jira-secret", allowed_workspace_root=tmp_path)
    client = TestClient(app)
    body = json.dumps(
        {
            "webhookEvent": "jira:issue_created",
            "repo_root": str(repo_root),
            "issue": {"key": "PROJ-42", "fields": {"summary": "Order", "description": ""}},
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/jira",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature": "sha256=bad",
        },
    )

    assert response.status_code == 401


def test_jira_webhook_bearer_fallback_when_secret_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PMCURSOR_JIRA_WEBHOOK_SECRET", raising=False)
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(api_token="jira-bearer-token", allowed_workspace_root=tmp_path)
    client = TestClient(app)
    payload: dict[str, Any] = {
        "webhookEvent": "jira:issue_updated",
        "repo_root": str(repo_root),
        "issue": {
            "key": "PROJ-77",
            "fields": {"summary": "Order schema", "description": _sample_prd()},
        },
    }

    unauth = client.post("/v1/webhooks/jira", json=payload)
    assert unauth.status_code == 401

    auth = client.post(
        "/v1/webhooks/jira",
        json=payload,
        headers={"Authorization": "Bearer jira-bearer-token"},
    )
    assert auth.status_code == 200
    report = TicketSyncReport.model_validate(auth.json())
    assert report.provider == "jira"
    assert report.ticket_id == "PROJ-77"


def test_jira_webhook_non_issue_event_is_ignored(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    secret = "jira-secret"
    app = create_app(jira_webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)
    body = json.dumps(
        {
            "webhookEvent": "sprint_closed",
            "repo_root": str(repo_root),
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/jira",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature": _sign_jira(body, secret),
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "webhook_event": "sprint_closed"}
