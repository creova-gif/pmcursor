from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from pmcursor.cli import main as cli_main
from pmcursor.release_notes import ReleaseNotesReport


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
        "@@ -3,3 +3,3 @@\n"
        " class Order(BaseModel):\n"
        "     order_id: str\n"
        "-    total_cents: int\n"
        "+    total_cents: int\n"
    )


def test_release_notes_endpoint_requires_auth_returns_401(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(api_token="top-secret-token")
    client = TestClient(app)
    payload = {
        "prd_markdown": _sample_prd(),
        "diff_text": _sample_diff(),
        "repo_root": str(repo_root),
    }

    missing_response = client.post("/v1/release-notes", json=payload)
    wrong_response = client.post(
        "/v1/release-notes",
        json=payload,
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert missing_response.status_code == 401
    assert wrong_response.status_code == 401


def test_release_notes_endpoint_escaping_workspace_returns_403(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _create_sample_repo(tmp_path / "outside")
    app = create_app(allowed_workspace_root=workspace)
    client = TestClient(app)
    payload = {
        "prd_markdown": _sample_prd(),
        "diff_text": _sample_diff(),
        "repo_root": str(outside),
    }

    response = client.post("/v1/release-notes", json=payload)

    assert response.status_code == 403


def test_release_notes_endpoint_missing_repo_returns_404(tmp_path: Path) -> None:
    app = create_app()
    client = TestClient(app)
    payload = {
        "prd_markdown": _sample_prd(),
        "diff_text": _sample_diff(),
        "repo_root": str(tmp_path / "does-not-exist"),
    }

    response = client.post("/v1/release-notes", json=payload)

    assert response.status_code == 404


def test_release_notes_endpoint_returns_200(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    app = create_app(api_token="secret-token", allowed_workspace_root=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/v1/release-notes",
        json={
            "prd_markdown": _sample_prd(),
            "diff_text": _sample_diff(),
            "repo_root": str(repo_root),
            "prd_path": "PRD.md",
            "version": "v1.2.0",
        },
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    report = ReleaseNotesReport.model_validate(response.json())
    assert report.version == "v1.2.0"
    assert report.prd_path == "PRD.md"
    assert report.changed_files_count == 1
    assert any(entry.name == "Order" and entry.covered_in_prd for entry in report.entries)
    assert "v1.2.0" in report.markdown


def test_cli_release_notes_diff_file_json_and_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _create_sample_repo(tmp_path)
    prd_file = tmp_path / "PRD.md"
    prd_file.write_text(_sample_prd(), encoding="utf-8")
    diff_file = tmp_path / "changes.diff"
    diff_file.write_text(_sample_diff(), encoding="utf-8")
    out_file = tmp_path / "nested" / "RELEASE_NOTES.md"

    exit_json = cli_main(
        [
            "release-notes",
            "--prd",
            str(prd_file),
            "--repo",
            str(repo_root),
            "--diff-file",
            str(diff_file),
            "--version",
            "v2.0.0",
            "--json",
        ]
    )
    captured_json = capsys.readouterr()
    assert exit_json == 0
    report = ReleaseNotesReport.model_validate_json(captured_json.out)
    assert report.version == "v2.0.0"
    assert any(entry.name == "Order" for entry in report.entries)

    exit_out = cli_main(
        [
            "release-notes",
            "--prd",
            str(prd_file),
            "--repo",
            str(repo_root),
            "--diff-file",
            str(diff_file),
            "--version",
            "v2.0.0",
            "--output",
            str(out_file),
        ]
    )
    assert exit_out == 0
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "v2.0.0" in content
    assert "Order" in content


def test_cli_release_notes_missing_inputs_returns_2(tmp_path: Path) -> None:
    repo_root = _create_sample_repo(tmp_path)
    prd_file = tmp_path / "PRD.md"
    prd_file.write_text(_sample_prd(), encoding="utf-8")

    assert (
        cli_main(
            [
                "release-notes",
                "--prd",
                str(tmp_path / "missing.md"),
                "--repo",
                str(repo_root),
            ]
        )
        == 2
    )
    assert (
        cli_main(
            [
                "release-notes",
                "--prd",
                str(prd_file),
                "--repo",
                str(tmp_path / "missing-repo"),
            ]
        )
        == 2
    )
    assert (
        cli_main(
            [
                "release-notes",
                "--prd",
                str(prd_file),
                "--repo",
                str(repo_root),
                "--diff-file",
                str(tmp_path / "missing.diff"),
            ]
        )
        == 2
    )
