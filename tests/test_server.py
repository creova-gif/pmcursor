from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.server import create_app
from pmcursor.models import DriftReport, PRImpactReport

REPO_ROOT = Path(__file__).resolve().parent.parent


def _sign_payload(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


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


def _sample_diff() -> str:
    return (
        "diff --git a/app/models.py b/app/models.py\n"
        "--- a/app/models.py\n"
        "+++ b/app/models.py\n"
        "@@ -4,2 +4,2 @@ class Order(BaseModel):\n"
        "-    total_cents: float\n"
        "+    total_cents: int\n"
    )


def test_health_endpoint() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_drift_audit_endpoint(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/v1/drift/audit",
        json={
            "prd_markdown": _sample_prd(),
            "repo_root": str(repo_root),
            "prd_path": "PRD.md",
        },
    )

    assert response.status_code == 200
    report = DriftReport.model_validate(response.json())
    assert report.status == "DONE"


def test_github_webhook_invalid_signature(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    secret = "whsec_test_secret"
    app = create_app(webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)

    body = json.dumps(
        {
            "org_id": "acme",
            "prd_markdown": _sample_prd(),
            "diff_text": _sample_diff(),
            "prd_path": "PRD.md",
            "repo_root": str(repo_root),
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )

    assert response.status_code == 401


def test_github_webhook_escaping_repo_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _create_sample_repo(tmp_path / "outside")
    secret = "whsec_test_secret"
    app = create_app(webhook_secret=secret, allowed_workspace_root=workspace)
    client = TestClient(app)

    body = json.dumps(
        {
            "org_id": "acme",
            "prd_markdown": _sample_prd(),
            "diff_text": _sample_diff(),
            "prd_path": "PRD.md",
            "repo_root": str(outside),
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign_payload(body, secret),
        },
    )

    assert response.status_code == 401


def test_github_webhook_malformed_json(tmp_path: Path) -> None:
    secret = "whsec_test_secret"
    app = create_app(webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)

    body = b"{not-valid-json"

    response = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign_payload(body, secret),
        },
    )

    assert response.status_code == 422


def test_github_webhook_valid_payload(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    secret = "whsec_test_secret"
    app = create_app(webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)

    body = json.dumps(
        {
            "org_id": "acme",
            "prd_markdown": _sample_prd(),
            "diff_text": _sample_diff(),
            "prd_path": "PRD.md",
            "repo_root": str(repo_root),
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign_payload(body, secret),
        },
    )

    assert response.status_code == 200
    report = PRImpactReport.model_validate(response.json())
    assert len(report.touched_contracts) >= 1
    assert any(item.name == "Order" for item in report.touched_contracts)


def test_github_action_exists_and_invokes_drift() -> None:
    action_path = REPO_ROOT / ".github" / "actions" / "pmcursor-drift" / "action.yml"

    assert action_path.is_file()
    content = action_path.read_text(encoding="utf-8")
    assert "pmcursor" in content
    assert "drift" in content
