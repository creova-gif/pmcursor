from __future__ import annotations

import hashlib
import hmac
import importlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from api.server import _is_authorized, app, create_app, run_server
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


def test_drift_audit_missing_repo_root_returns_404(tmp_path: Path) -> None:
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/v1/drift/audit",
        json={
            "prd_markdown": _sample_prd(),
            "repo_root": str(tmp_path / "does-not-exist"),
            "prd_path": "PRD.md",
        },
    )

    assert response.status_code == 404


def test_drift_audit_escaping_workspace_returns_403(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _create_sample_repo(tmp_path / "outside")
    app = create_app(allowed_workspace_root=workspace)
    client = TestClient(app)

    response = client.post(
        "/v1/drift/audit",
        json={
            "prd_markdown": _sample_prd(),
            "repo_root": str(outside),
            "prd_path": "PRD.md",
        },
    )

    assert response.status_code == 403


def test_drift_audit_requires_api_token_when_configured(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(api_token="top-secret-token")
    client = TestClient(app)
    payload = {
        "prd_markdown": _sample_prd(),
        "repo_root": str(repo_root),
        "prd_path": "PRD.md",
    }

    missing_response = client.post("/v1/drift/audit", json=payload)
    wrong_response = client.post(
        "/v1/drift/audit",
        json=payload,
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert missing_response.status_code == 401
    assert wrong_response.status_code == 401


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


def test_github_webhook_native_pull_request_accepted(tmp_path: Path) -> None:
    secret = "whsec_test_secret"
    app = create_app(webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)

    body = json.dumps(
        {
            "action": "opened",
            "number": 42,
            "pull_request": {
                "number": 42,
                "title": "Update Order model",
                "html_url": "https://github.com/acme/repo/pull/42",
            },
            "repository": {"full_name": "acme/repo"},
        }
    ).encode("utf-8")

    response = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign_payload(body, secret),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"


def test_github_webhook_ping_returns_pong(tmp_path: Path) -> None:
    secret = "whsec_test_secret"
    app = create_app(webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)

    body = json.dumps({"zen": "Keep it logically awesome.", "hook_id": 1}).encode("utf-8")

    response = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign_payload(body, secret),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pong"


def test_github_action_exists_and_invokes_drift() -> None:
    action_path = REPO_ROOT / ".github" / "actions" / "pmcursor-drift" / "action.yml"

    assert action_path.is_file()
    content = action_path.read_text(encoding="utf-8")
    assert "pmcursor" in content
    assert "drift" in content
    assert "INPUT_PRD: ${{ inputs.prd }}" in content
    assert "INPUT_REPO: ${{ inputs.repo }}" in content
    assert "INPUT_FAIL_ON_DRIFT: ${{ inputs.fail-on-drift }}" in content
    assert "ACTION_PATH: ${{ github.action_path }}" in content

    run_lines: list[str] = []
    in_run_block = False
    run_indent = 0
    for line in content.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if in_run_block:
            if stripped and indent <= run_indent:
                in_run_block = False
            else:
                run_lines.append(line)
                continue
        if stripped.startswith("run:"):
            run_lines.append(stripped[len("run:") :])
            if stripped.endswith(("|", ">")):
                in_run_block = True
                run_indent = indent

    run_script = "\n".join(run_lines)
    assert "${{ inputs." not in run_script
    assert "${{ github.action_path }}" not in run_script



def test_drift_audit_lowercase_bearer_and_non_ascii_token(tmp_path: Path) -> None:
    (tmp_path / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass Ping(BaseModel):\n    ok: bool\n",
        encoding="utf-8",
    )
    app = create_app(
        allowed_workspace_root=tmp_path,
        api_token="ascii-secret-token",
    )
    client = TestClient(app)

    res_bearer = client.post(
        "/v1/drift/audit",
        json={"prd_markdown": "# PRD\n", "repo_root": str(tmp_path)},
        headers={"Authorization": "bearer  ascii-secret-token "},
    )
    assert res_bearer.status_code == 200

    res_header = client.post(
        "/v1/drift/audit",
        json={"prd_markdown": "# PRD\n", "repo_root": str(tmp_path)},
        headers={"X-PMCursor-Token": "ascii-secret-token"},
    )
    assert res_header.status_code == 200

    assert _is_authorized("tökén-secret-🔑", "bearer  tökén-secret-🔑 ", "") is True
    assert _is_authorized("tökén-secret-🔑", "", "tökén-secret-🔑") is True
    assert _is_authorized("tökén-secret-🔑", "", "wrong") is False


def test_github_webhook_form_encoded_pull_request(tmp_path: Path) -> None:
    secret = "whsec_server_secret"
    app = create_app(webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)

    payload_json = json.dumps(
        {
            "action": "synchronize",
            "number": 7,
            "pull_request": {"number": 7, "title": "Update contract"},
            "repository": {"full_name": "creova-gif/pmcursor"},
        }
    )
    body = urlencode({"payload": payload_json}).encode("utf-8")
    sig = _sign_payload(body, secret)

    response = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data["pr_number"] == 7


def test_drift_audit_ignores_out_of_workspace_symlinks(tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    workspace = tmp_path / "workspace"
    outside_dir.mkdir()
    workspace.mkdir()
    secret_py = outside_dir / "secret.py"
    secret_py.write_text(
        "from pydantic import BaseModel\n\nclass SecretModel(BaseModel):\n    key: str\n",
        encoding="utf-8",
    )
    (workspace / "leak.py").symlink_to(secret_py)
    (workspace / "local.py").write_text(
        "from pydantic import BaseModel\n\nclass LocalModel(BaseModel):\n    id: str\n",
        encoding="utf-8",
    )

    app = create_app(allowed_workspace_root=workspace)
    client = TestClient(app)
    res = client.post(
        "/v1/drift/audit",
        json={
            "prd_markdown": "# PRD\n- `SecretModel.key: str`\n- `LocalModel.id: str`\n",
            "repo_root": str(workspace),
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert any(
        f["category"] == "missing_model" and "SecretModel" in f["spec_reference"]
        for f in data["findings"]
    )


def test_drift_audit_latin1_decoded_utf8_header(tmp_path: Path) -> None:
    (tmp_path / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass Ping(BaseModel):\n    ok: bool\n",
        encoding="utf-8",
    )
    token = "tökén-secret-🔑"
    wire_latin1 = token.encode("utf-8").decode("latin-1")
    assert _is_authorized(token, f"Bearer {wire_latin1}", "") is True
    assert _is_authorized(token, "", wire_latin1) is True


def test_github_webhook_form_encoded_pr_impact_payload(tmp_path: Path) -> None:
    (tmp_path / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass Order(BaseModel):\n    order_id: str\n",
        encoding="utf-8",
    )
    secret = "whsec_server_secret"
    app = create_app(webhook_secret=secret, allowed_workspace_root=tmp_path)
    client = TestClient(app)

    payload_json = json.dumps(
        {
            "org_id": "acme",
            "prd_markdown": "# Order PRD\n- `Order.order_id: str`\n",
            "diff_text": (
                "diff --git a/models.py b/models.py\n"
                "--- a/models.py\n"
                "+++ b/models.py\n"
                "@@ -3,2 +3,2 @@ class Order(BaseModel):\n"
                "     order_id: str\n"
            ),
            "prd_path": "PRD.md",
            "repo_root": str(tmp_path),
        }
    )
    body = urlencode({"payload": payload_json}).encode("utf-8")
    sig = _sign_payload(body, secret)

    response = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["org_id"] == "acme"
    assert len(data["touched_contracts"]) == 1
    assert data["touched_contracts"][0]["name"] == "Order"


def _patch_fake_uvicorn(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class _FakeUvicorn:
        def run(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

    def _fake_import_module(name: str, package: str | None = None) -> Any:
        assert name == "uvicorn"
        return _FakeUvicorn()

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)
    return calls


def test_run_server_non_loopback_without_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PMCURSOR_API_TOKEN", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    calls = _patch_fake_uvicorn(monkeypatch)

    with pytest.raises(ValueError, match="PMCURSOR_API_TOKEN"):
        run_server(host="0.0.0.0", port=8000)

    assert calls == []


def test_run_server_non_loopback_with_token_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PMCURSOR_API_TOKEN", "secret-token")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    calls = _patch_fake_uvicorn(monkeypatch)

    run_server(host="0.0.0.0", port=8000)

    assert calls == [((app,), {"host": "0.0.0.0", "port": 8000})]


def test_run_server_loopback_without_token_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PMCURSOR_API_TOKEN", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    calls = _patch_fake_uvicorn(monkeypatch)

    run_server(host="127.0.0.1", port=8000)

    assert calls == [((app,), {"host": "127.0.0.1", "port": 8000})]


def test_run_server_web_concurrency_multi_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PMCURSOR_API_TOKEN", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    calls = _patch_fake_uvicorn(monkeypatch)

    run_server(host="127.0.0.1", port=8000)

    assert calls == [
        (("api.server:app",), {"host": "127.0.0.1", "port": 8000, "workers": 2})
    ]


def test_run_server_invalid_web_concurrency_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PMCURSOR_API_TOKEN", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "0")
    _patch_fake_uvicorn(monkeypatch)

    with pytest.raises(ValueError, match="WEB_CONCURRENCY"):
        run_server(host="127.0.0.1", port=8000)


def test_run_server_missing_uvicorn_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PMCURSOR_API_TOKEN", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    def _missing_import(name: str, package: str | None = None) -> Any:
        raise ModuleNotFoundError("No module named 'uvicorn'")

    monkeypatch.setattr(importlib, "import_module", _missing_import)

    with pytest.raises(RuntimeError, match="pmcursor\\[server\\]"):
        run_server(host="127.0.0.1", port=8000)
