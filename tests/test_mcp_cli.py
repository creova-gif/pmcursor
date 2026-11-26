from __future__ import annotations

import json
from pathlib import Path

import pytest

import pmcursor
import pmcursor.cli as cli_module


def test_mcp_parser_workspace_root() -> None:
    args = cli_module.build_parser().parse_args(["mcp", "--workspace-root", "."])
    assert args.command == "mcp"
    assert args.workspace_root == Path(".")


def test_mcp_main_invokes_run_mcp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    called_with: list[Path | None] = []

    def _fake_run_mcp_server(*, allowed_workspace_root: Path | None = None) -> None:
        called_with.append(allowed_workspace_root)

    monkeypatch.setattr(cli_module, "run_mcp_server", _fake_run_mcp_server)

    exit_code = cli_module.main(["mcp"])

    assert exit_code == 0
    assert called_with == [None]


def test_mcp_main_passes_workspace_root(monkeypatch: pytest.MonkeyPatch) -> None:
    called_with: list[Path | None] = []

    def _fake_run_mcp_server(*, allowed_workspace_root: Path | None = None) -> None:
        called_with.append(allowed_workspace_root)

    monkeypatch.setattr(cli_module, "run_mcp_server", _fake_run_mcp_server)

    exit_code = cli_module.main(["mcp", "--workspace-root", "."])

    assert exit_code == 0
    assert called_with == [Path(".")]


def test_top_level_mcp_exports() -> None:
    for symbol in ("PMCursorMCPServer", "RepoIndexCache", "run_mcp_server"):
        assert hasattr(pmcursor, symbol)
        assert symbol in pmcursor.__all__


def test_mcp_json_config() -> None:
    mcp_json_path = Path(".mcp.json")
    data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    server = data["mcpServers"]["pmcursor"]
    assert server["command"] == "python3"
    assert "pmcursor.cli" in server["args"]
    assert "mcp" in server["args"]
    assert server["env"]["PYTHONPATH"] == "src"
