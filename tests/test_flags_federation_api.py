from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.server import create_app
from pmcursor.feature_flags import FlagAuditReport


def _create_flag_repo(base: Path) -> Path:
    app_dir = base / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "flags.py").write_text(
        "def is_checkout_v2(ld_client, user) -> bool:\n"
        '    return ld_client.bool_variation("checkout-v2", user, False)\n\n'
        "def is_legacy_flow(unleash_client) -> bool:\n"
        '    return unleash_client.is_enabled("legacy-flow")\n',
        encoding="utf-8",
    )
    return base


def _sample_flag_prd() -> str:
    return (
        "# Checkout v2 PRD\n\n"
        "## Feature Flags\n"
        "- flag: checkout-v2\n"
        "- flag: missing-in-code-flag\n\n"
        "## Rollback Plan\n"
        "- Disable `checkout-v2` kill-switch in LaunchDarkly.\n"
    )


def test_flags_audit_endpoint_requires_auth_returns_401(tmp_path: Path) -> None:
    repo_root = _create_flag_repo(tmp_path)
    app = create_app(api_token="top-secret-token")
    client = TestClient(app)
    payload = {
        "prd_markdown": _sample_flag_prd(),
        "repo_root": str(repo_root),
    }

    missing_response = client.post("/v1/flags/audit", json=payload)
    wrong_response = client.post(
        "/v1/flags/audit",
        json=payload,
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert missing_response.status_code == 401
    assert wrong_response.status_code == 401


def test_flags_audit_endpoint_escaping_workspace_returns_403(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _create_flag_repo(tmp_path / "outside")
    app = create_app(allowed_workspace_root=workspace)
    client = TestClient(app)
    payload = {
        "prd_markdown": _sample_flag_prd(),
        "repo_root": str(outside),
    }

    response = client.post("/v1/flags/audit", json=payload)

    assert response.status_code == 403


def test_flags_audit_endpoint_missing_repo_returns_404(tmp_path: Path) -> None:
    app = create_app()
    client = TestClient(app)
    payload = {
        "prd_markdown": _sample_flag_prd(),
        "repo_root": str(tmp_path / "does-not-exist"),
    }

    response = client.post("/v1/flags/audit", json=payload)

    assert response.status_code == 404


def test_flags_audit_endpoint_returns_200(tmp_path: Path) -> None:
    repo_root = _create_flag_repo(tmp_path)
    app = create_app(api_token="secret-token", allowed_workspace_root=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/flags/audit",
        json={
            "prd_markdown": _sample_flag_prd(),
            "repo_root": str(repo_root),
        },
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    report = FlagAuditReport.model_validate(response.json())
    assert report.total_repo_flags == 2
    assert report.referenced_flags == ["checkout-v2"]
    assert report.missing_prd_flags == ["missing-in-code-flag"]
    assert report.undocumented_repo_flags == ["legacy-flow (app/flags.py:5)"]
    assert report.rollback_ready is True
    assert "## Feature Flag & Rollout Audit" in report.markdown
    assert "missing-in-code-flag" in report.markdown
    assert "legacy-flow (app/flags.py:5)" in report.markdown
