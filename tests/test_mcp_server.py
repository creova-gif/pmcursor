from __future__ import annotations

import concurrent.futures
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest

import pmcursor.mcp_server as mcp_server_module
from pmcursor.indexer import index_repository
from pmcursor.mcp_server import PMCursorMCPServer, RepoIndexCache, run_mcp_server
from pmcursor.models import RepoMap


def _build_sample_repo(root: Path) -> Path:
    repo = root / "sample_repo"
    src_dir = repo / "src"
    adr_dir = repo / "docs" / "adr"
    src_dir.mkdir(parents=True)
    adr_dir.mkdir(parents=True)

    (src_dir / "schemas.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class WidgetSpec(BaseModel):\n"
        "    widget_id: str\n"
        "    title: str\n"
        "    priority: int = 1\n",
        encoding="utf-8",
    )
    (src_dir / "routes.py").write_text(
        "from fastapi import FastAPI\n"
        "from src.schemas import WidgetSpec\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/widgets/{widget_id}', response_model=WidgetSpec)\n"
        "def get_widget(widget_id: str) -> WidgetSpec:\n"
        "    return WidgetSpec(widget_id=widget_id, title='Sample')\n",
        encoding="utf-8",
    )
    (adr_dir / "001-widgets.md").write_text(
        "# ADR-001: Widget Contracts\n- **Status:** Accepted\n",
        encoding="utf-8",
    )
    return repo


def _sample_prd() -> str:
    return (
        "# Widget PRD\n\n"
        "## Acceptance Cards\n"
        "- `WidgetSpec` (`src/schemas.py:3`) has `widget_id: str`, `title: str`, `priority: int`.\n"
        "- `GET /widgets/{widget_id}` (`src/routes.py:6`) returns `WidgetSpec`.\n\n"
        "## ADR References\n"
        "- `ADR-001` (`docs/adr/001-widgets.md:1`)\n\n"
        "## Out of Scope\n"
        "- Bulk import.\n\n"
        "## Rollback Plan\n"
        "- Disable widget endpoint.\n"
    )


def test_repo_index_cache_hit_and_invalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _build_sample_repo(tmp_path)
    ignored_dir = repo / "__pycache__"
    ignored_dir.mkdir()
    (ignored_dir / "cached.pyc").write_bytes(b"abc")

    call_count = 0

    def spy_index_repository(repo_root: Path) -> RepoMap:
        nonlocal call_count
        call_count += 1
        return index_repository(repo_root)

    monkeypatch.setattr(mcp_server_module, "index_repository", spy_index_repository)

    cache = RepoIndexCache()
    first = cache.get_or_index(repo)
    second = cache.get_or_index(repo)

    assert call_count == 1
    assert second is first

    # Touching a skipped directory must not invalidate the cache.
    (ignored_dir / "cached.pyc").write_bytes(b"abcdef")
    third = cache.get_or_index(repo)
    assert call_count == 1
    assert third is first

    # Editing a tracked file invalidates the cache and triggers re-indexing.
    schemas_file = repo / "src" / "schemas.py"
    original = schemas_file.read_text(encoding="utf-8")
    schemas_file.write_text(original + "    active: bool = True\n", encoding="utf-8")
    stat_res = schemas_file.stat()
    os.utime(schemas_file, ns=(stat_res.st_atime_ns, stat_res.st_mtime_ns + 1_000_000))

    fourth = cache.get_or_index(repo)
    assert call_count == 2
    assert fourth is not first
    field_names = {f.name for m in fourth.models for f in m.fields}
    assert "active" in field_names


def test_mcp_server_protocol_and_tools_over_stdio(tmp_path: Path) -> None:
    repo = _build_sample_repo(tmp_path)
    prd_md = _sample_prd()
    diff_text = (
        "diff --git a/src/schemas.py b/src/schemas.py\n"
        "--- a/src/schemas.py\n"
        "+++ b/src/schemas.py\n"
        "@@ -3,3 +3,4 @@\n"
        " class WidgetSpec(BaseModel):\n"
        "     widget_id: str\n"
        "     title: str\n"
        "+    priority: int = 1\n"
    )

    requests: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "pmcursor_index", "arguments": {"repo_root": str(repo)}},
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "pmcursor_drift",
                "arguments": {"repo_root": str(repo), "prd_markdown": prd_md},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "pmcursor_checklist",
                "arguments": {"repo_root": str(repo), "prd_markdown": prd_md},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "pmcursor_ticket_sync",
                "arguments": {
                    "repo_root": str(repo),
                    "ticket_id": "ENG-42",
                    "title": "Widget API",
                    "description": prd_md,
                    "provider": "linear",
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "pmcursor_release_notes",
                "arguments": {
                    "repo_root": str(repo),
                    "prd_markdown": prd_md,
                    "diff_text": diff_text,
                    "version": "v0.1.0",
                },
            },
        },
    ]

    stdin_buf = io.StringIO("\n".join(json.dumps(req) for req in requests) + "\n")
    stdout_buf = io.StringIO()

    run_mcp_server(stdin=stdin_buf, stdout=stdout_buf, allowed_workspace_root=tmp_path)

    raw_lines = [line for line in stdout_buf.getvalue().splitlines() if line.strip()]
    # 9 requests minus 1 notification = 8 responses.
    assert len(raw_lines) == 8
    responses: dict[int, dict[str, Any]] = {
        resp["id"]: resp for resp in (json.loads(line) for line in raw_lines)
    }

    init_res = responses[1]["result"]
    assert init_res["protocolVersion"] == "2024-11-05"
    assert init_res["capabilities"] == {"tools": {}}
    assert init_res["serverInfo"] == {"name": "pmcursor", "version": "0.3.0"}

    assert responses[2]["result"] == {}

    tools = responses[3]["result"]["tools"]
    tool_names = [tool["name"] for tool in tools]
    assert tool_names == [
        "pmcursor_index",
        "pmcursor_drift",
        "pmcursor_checklist",
        "pmcursor_ticket_sync",
        "pmcursor_release_notes",
        "pmcursor_flags",
        "pmcursor_telemetry_verify",
    ]

    for call_id in (4, 5, 6, 7, 8):
        call_res = responses[call_id]["result"]
        assert call_res["isError"] is False
        assert len(call_res["content"]) == 1
        assert call_res["content"][0]["type"] == "text"

    index_payload = json.loads(responses[4]["result"]["content"][0]["text"])
    assert any(m["name"] == "WidgetSpec" for m in index_payload["models"])
    assert any(r["path"] == "/widgets/{widget_id}" for r in index_payload["routes"])

    drift_payload = json.loads(responses[5]["result"]["content"][0]["text"])
    assert drift_payload["status"] == "DONE"

    checklist_payload = json.loads(responses[6]["result"]["content"][0]["text"])
    assert checklist_payload["total_items"] >= 1

    ticket_payload = json.loads(responses[7]["result"]["content"][0]["text"])
    assert ticket_payload["ticket_id"] == "ENG-42"
    assert ticket_payload["provider"] == "linear"

    release_payload = json.loads(responses[8]["result"]["content"][0]["text"])
    assert release_payload["version"] == "v0.1.0"
    assert any(e["name"] == "WidgetSpec" for e in release_payload["entries"])


def test_mcp_server_error_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    stdin_lines = [
        "{invalid json",
        json.dumps({"jsonrpc": "2.0", "id": 10, "method": "unknown/method"}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "nonexistent_tool", "arguments": {}},
            }
        ),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "pmcursor_index", "arguments": {}},
            }
        ),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {
                    "name": "pmcursor_index",
                    "arguments": {"repo_root": str(outside)},
                },
            }
        ),
    ]

    stdin_buf = io.StringIO("\n".join(stdin_lines) + "\n")
    stdout_buf = io.StringIO()

    run_mcp_server(stdin=stdin_buf, stdout=stdout_buf, allowed_workspace_root=workspace)

    responses = [json.loads(line) for line in stdout_buf.getvalue().splitlines() if line.strip()]
    assert len(responses) == 5

    # -32700 parse error
    assert responses[0]["id"] is None
    assert responses[0]["error"]["code"] == -32700

    # -32601 method not found
    assert responses[1]["id"] == 10
    assert responses[1]["error"]["code"] == -32601

    # -32602 unknown tool
    assert responses[2]["id"] == 11
    assert responses[2]["error"]["code"] == -32602

    # -32602 missing required argument
    assert responses[3]["id"] == 12
    assert responses[3]["error"]["code"] == -32602

    # allowed_workspace_root escape -> tool error with isError: True
    assert responses[4]["id"] == 13
    assert responses[4]["result"]["isError"] is True
    err_body = json.loads(responses[4]["result"]["content"][0]["text"])
    assert err_body["error_type"] == "PermissionError"


def test_mcp_server_missing_repo_dir_returns_is_error(tmp_path: Path) -> None:
    server = PMCursorMCPServer(allowed_workspace_root=tmp_path)
    resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "pmcursor_index",
                "arguments": {"repo_root": str(tmp_path / "does_not_exist")},
            },
        }
    )
    assert resp is not None
    assert resp["result"]["isError"] is True
    err_body = json.loads(resp["result"]["content"][0]["text"])
    assert err_body["error_type"] == "FileNotFoundError"


def test_repo_index_cache_lru_eviction_and_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="max_entries"):
        RepoIndexCache(max_entries=0)

    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_c = tmp_path / "repo_c"
    for repo_dir in (repo_a, repo_b, repo_c):
        (repo_dir / "src").mkdir(parents=True)
        (repo_dir / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")

    indexed_paths: list[Path] = []

    def spy_index_repository(repo_root: Path) -> RepoMap:
        indexed_paths.append(repo_root)
        return index_repository(repo_root)

    monkeypatch.setattr(mcp_server_module, "index_repository", spy_index_repository)

    cache = RepoIndexCache(max_entries=2)
    assert cache.hits == 0
    assert cache.misses == 0

    map_a1 = cache.get_or_index(repo_a)
    assert cache.misses == 1
    assert cache.hits == 0
    assert cache.size == 1

    _ = cache.get_or_index(repo_b)
    assert cache.misses == 2
    assert cache.hits == 0
    assert cache.size == 2

    # Touch repo_a so repo_b becomes the least-recently-used entry.
    map_a2 = cache.get_or_index(repo_a)
    assert map_a2 is map_a1
    assert cache.hits == 1
    assert cache.misses == 2

    # Indexing repo_c should evict repo_b, keeping repo_a and repo_c.
    _ = cache.get_or_index(repo_c)
    assert cache.size == 2
    assert cache.misses == 3
    assert cache.hits == 1

    # repo_a is still cached (hit); repo_b was evicted (miss).
    assert cache.get_or_index(repo_a) is map_a1
    assert cache.hits == 2
    assert cache.misses == 3

    _ = cache.get_or_index(repo_b)
    assert cache.misses == 4
    assert cache.size == 2
    assert indexed_paths == [
        repo_a.resolve(),
        repo_b.resolve(),
        repo_c.resolve(),
        repo_b.resolve(),
    ]


def test_mcp_server_flags_and_telemetry_verify_tools(tmp_path: Path) -> None:
    repo = _build_sample_repo(tmp_path)
    (repo / "src" / "flags.py").write_text(
        "def check_widget_flag() -> bool:\n"
        "    return is_enabled('enable_widget_v2')\n",
        encoding="utf-8",
    )
    (repo / "src" / "analytics.py").write_text(
        "def track_widget_viewed(widget_id: str) -> None:\n"
        "    track_event('widget_viewed', {'widget_id': widget_id, 'source': 'web'})\n",
        encoding="utf-8",
    )

    prd_with_flag = _sample_prd() + "\n## Feature Flags\n- `enable_widget_v2`\n"

    server = PMCursorMCPServer(allowed_workspace_root=tmp_path)

    flags_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "pmcursor_flags",
                "arguments": {"repo_root": str(repo), "prd_markdown": prd_with_flag},
            },
        }
    )
    assert flags_resp is not None
    assert flags_resp["result"]["isError"] is False
    flags_payload = json.loads(flags_resp["result"]["content"][0]["text"])
    assert "enable_widget_v2" in flags_payload["referenced_flags"]
    assert flags_payload["rollback_ready"] is True

    telemetry_resp = server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {
                "name": "pmcursor_telemetry_verify",
                "arguments": {
                    "repo_root": str(repo),
                    "events": [
                        {
                            "event_name": "widget_viewed",
                            "properties": {"widget_id": "w-1", "source": "web"},
                        }
                    ],
                },
            },
        }
    )
    assert telemetry_resp is not None
    assert telemetry_resp["result"]["isError"] is False
    telemetry_payload = json.loads(telemetry_resp["result"]["content"][0]["text"])
    assert telemetry_payload["matched_events"] == 1
    assert telemetry_payload["total_code_events"] == 1
    assert telemetry_payload["items"][0]["status"] == "matched"


def test_repo_index_cache_thread_safety(tmp_path: Path) -> None:
    repos = [_build_sample_repo(tmp_path / f"ws_{idx}") for idx in range(4)]
    cache = RepoIndexCache(max_entries=2)
    targets = [repos[i % len(repos)] for i in range(64)]
    total_calls = len(targets)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cache.get_or_index, repo) for repo in targets]
        results = [future.result() for future in futures]

    assert len(results) == total_calls
    assert all(isinstance(repo_map, RepoMap) for repo_map in results)
    assert cache.hits + cache.misses == total_calls
    assert cache.size <= 2
