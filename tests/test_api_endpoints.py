from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from pmcursor.checklists import EdgeCaseChecklist
from pmcursor.cli import main as cli_main
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


def _payload_for_endpoint(endpoint: str, repo_root: Path) -> dict[str, Any]:
    if endpoint == "/v1/tickets/audit":
        return {
            "ticket_id": "ENG-42",
            "title": "Order schema",
            "description": _sample_prd(),
            "provider": "linear",
            "repo_root": str(repo_root),
        }
    if endpoint == "/v1/checklist":
        return {
            "repo_root": str(repo_root),
            "prd_markdown": _sample_prd(),
        }
    if endpoint == "/v1/canvas":
        return {
            "prd_markdown": _sample_prd(),
            "repo_root": str(repo_root),
            "prd_path": "PRD.md",
        }
    raise ValueError(f"Unsupported endpoint: {endpoint}")


@pytest.mark.parametrize(
    "endpoint",
    ["/v1/tickets/audit", "/v1/checklist", "/v1/canvas"],
)
def test_endpoint_requires_api_token_returns_401(tmp_path: Path, endpoint: str) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(api_token="top-secret-token")
    client = TestClient(app)
    payload = _payload_for_endpoint(endpoint, repo_root)

    missing_response = client.post(endpoint, json=payload)
    wrong_response = client.post(
        endpoint,
        json=payload,
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert missing_response.status_code == 401
    assert wrong_response.status_code == 401


@pytest.mark.parametrize(
    "endpoint",
    ["/v1/tickets/audit", "/v1/checklist", "/v1/canvas"],
)
def test_endpoint_escaping_workspace_returns_403(tmp_path: Path, endpoint: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _create_sample_repo(tmp_path / "outside")
    app = create_app(allowed_workspace_root=workspace)
    client = TestClient(app)
    payload = _payload_for_endpoint(endpoint, outside)

    response = client.post(endpoint, json=payload)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "endpoint",
    ["/v1/tickets/audit", "/v1/checklist", "/v1/canvas"],
)
def test_endpoint_missing_repo_root_returns_404(tmp_path: Path, endpoint: str) -> None:
    app = create_app()
    client = TestClient(app)
    payload = _payload_for_endpoint(endpoint, tmp_path / "does-not-exist")

    response = client.post(endpoint, json=payload)

    assert response.status_code == 404


def test_tickets_audit_endpoint_returns_200(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(api_token="secret-token", allowed_workspace_root=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/tickets/audit",
        json=_payload_for_endpoint("/v1/tickets/audit", repo_root),
        headers={"X-PMCursor-Token": "secret-token"},
    )

    assert response.status_code == 200
    report = TicketSyncReport.model_validate(response.json())
    assert report.ticket_id == "ENG-42"
    assert report.provider == "linear"
    assert report.drift_report.status == "DONE"
    assert "ENG-42" in report.comment_markdown


def test_checklist_endpoint_returns_200(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(api_token="secret-token", allowed_workspace_root=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/checklist",
        json=_payload_for_endpoint("/v1/checklist", repo_root),
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    checklist = EdgeCaseChecklist.model_validate(response.json())
    assert checklist.total_items == len(checklist.items)
    assert checklist.p0_count >= 0
    assert checklist.markdown.strip() != ""


def test_canvas_endpoint_returns_200_html(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(api_token="secret-token", allowed_workspace_root=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/canvas",
        json=_payload_for_endpoint("/v1/canvas", repo_root),
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<html" in response.text.lower()
    assert "Order PRD" in response.text


def test_cli_checklist_stdout_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _create_sample_repo(tmp_path)

    exit_code_md = cli_main(["checklist", "--repo", str(repo_root)])
    captured_md = capsys.readouterr()
    assert exit_code_md == 0
    assert captured_md.out.strip() != ""

    exit_code_json = cli_main(["checklist", "--repo", str(repo_root), "--json"])
    captured_json = capsys.readouterr()
    assert exit_code_json == 0
    checklist = EdgeCaseChecklist.model_validate_json(captured_json.out)
    assert checklist.total_items == len(checklist.items)


def test_cli_checklist_prd_and_output_file(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    prd_file = tmp_path / "PRD.md"
    prd_file.write_text(_sample_prd(), encoding="utf-8")
    out_file = tmp_path / "nested" / "checklist.md"

    exit_code = cli_main(
        [
            "checklist",
            "--repo",
            str(repo_root),
            "--prd",
            str(prd_file),
            "--output",
            str(out_file),
        ]
    )

    assert exit_code == 0
    assert out_file.is_file()
    assert out_file.read_text(encoding="utf-8").strip() != ""


def test_cli_checklist_missing_repo_or_prd_returns_2(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)

    assert cli_main(["checklist", "--repo", str(tmp_path / "missing")]) == 2
    assert (
        cli_main(
            [
                "checklist",
                "--repo",
                str(repo_root),
                "--prd",
                str(tmp_path / "missing.md"),
            ]
        )
        == 2
    )
