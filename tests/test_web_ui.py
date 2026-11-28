from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.server import create_app

_UI_ROOT = Path(__file__).resolve().parent.parent / "ui"


def test_ui_package_json_declares_nextjs_app() -> None:
    pkg = json.loads((_UI_ROOT / "package.json").read_text())
    assert pkg["name"] == "pmcursor-ui"
    assert pkg["private"] is True
    assert "next" in pkg["dependencies"]
    assert "react" in pkg["dependencies"]
    assert "build" in pkg["scripts"]
    assert "typecheck" in pkg["scripts"]


def test_ui_proxy_route_targets_v1_and_injects_token() -> None:
    route = (_UI_ROOT / "app/api/pmcursor/[...path]/route.ts").read_text()
    assert "PMCURSOR_API_URL" in route
    assert "PMCURSOR_API_TOKEN" in route
    assert "/v1/" in route
    assert "Authorization" in route


def test_ui_workspace_is_client_component_using_bff_proxy() -> None:
    workspace = (_UI_ROOT / "components/Workspace.tsx").read_text()
    assert '"use client"' in workspace
    api_client = (_UI_ROOT / "lib/api.ts").read_text()
    assert "/api/pmcursor/" in api_client
    for endpoint in ("drift/audit", "index", "checklist"):
        assert endpoint in api_client


def test_ui_types_mirror_backend_models() -> None:
    types_src = (_UI_ROOT / "lib/types.ts").read_text()
    for model in (
        "RepoMap",
        "DriftReport",
        "DriftFinding",
        "ModelContract",
        "RouteContract",
        "TelemetryContract",
        "ADRContract",
        "SpecAlignmentScore",
        "EdgeCaseChecklist",
    ):
        assert f"interface {model}" in types_src
    for status in ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT"):
        assert status in types_src


def test_ui_pages_render_split_panes() -> None:
    page = (_UI_ROOT / "app/page.tsx").read_text()
    assert "Workspace" in page
    spec_pane = (_UI_ROOT / "components/SpecPane.tsx").read_text()
    contracts_pane = (_UI_ROOT / "components/ContractsPane.tsx").read_text()
    assert "Living PRD" in spec_pane
    assert "Repository Contracts" in contracts_pane


def test_ui_gitignore_excludes_build_artifacts() -> None:
    gitignore = (_UI_ROOT / ".gitignore").read_text()
    for entry in ("node_modules/", ".next/", "next-env.d.ts"):
        assert entry in gitignore


def test_api_index_endpoint_returns_repo_map(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "models.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class Order(BaseModel):\n"
        "    order_id: str\n",
        encoding="utf-8",
    )
    app = create_app()
    client = TestClient(app)
    resp = client.post("/v1/index", json={"repo_root": str(repo)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo_root"] == str(repo)
    assert any(m["name"] == "Order" for m in data["models"])


def test_api_index_endpoint_rejects_missing_repo(tmp_path: Path) -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.post("/v1/index", json={"repo_root": str(tmp_path / "nope")})
    assert resp.status_code == 404
