from __future__ import annotations

import json
import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, TextIO

from pmcursor.checklists import generate_edge_case_checklist
from pmcursor.drift import check_spec_drift
from pmcursor.feature_flags import audit_feature_flags_and_rollout
from pmcursor.indexer import index_repository
from pmcursor.models import RepoMap
from pmcursor.release_notes import generate_release_notes_and_coverage
from pmcursor.telemetry_verify import verify_telemetry_samples
from pmcursor.tickets import TicketProvider, audit_ticket_against_repo

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "pmcursor"
SERVER_VERSION = "0.2.0"

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)

FileFingerprint = tuple[str, int, int]
RepoFingerprint = tuple[FileFingerprint, ...]

_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "pmcursor_index",
        "description": (
            "Index a repository's models, routes, telemetry events, and ADRs into a RepoMap."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {
                    "type": "string",
                    "description": "Path to the repository root directory.",
                },
            },
            "required": ["repo_root"],
        },
    },
    {
        "name": "pmcursor_drift",
        "description": (
            "Check a PRD markdown specification for drift against the indexed codebase."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {
                    "type": "string",
                    "description": "Path to the repository root directory.",
                },
                "prd_markdown": {
                    "type": "string",
                    "description": "PRD markdown content to audit against the repository.",
                },
                "prd_path": {
                    "type": "string",
                    "description": "Optional logical path label for the PRD (default: PRD.md).",
                },
            },
            "required": ["repo_root", "prd_markdown"],
        },
    },
    {
        "name": "pmcursor_checklist",
        "description": (
            "Generate a codebase-cited edge-case and QA checklist from an indexed repository."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {
                    "type": "string",
                    "description": "Path to the repository root directory.",
                },
                "prd_markdown": {
                    "type": "string",
                    "description": "Optional PRD markdown to include P0 spec-drift items.",
                },
            },
            "required": ["repo_root"],
        },
    },
    {
        "name": "pmcursor_ticket_sync",
        "description": (
            "Audit a Linear or Jira ticket against the indexed codebase and generate a sync report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {
                    "type": "string",
                    "description": "Path to the repository root directory.",
                },
                "ticket_id": {
                    "type": "string",
                    "description": "Ticket identifier (e.g. ENG-123).",
                },
                "title": {
                    "type": "string",
                    "description": "Ticket title.",
                },
                "description": {
                    "type": "string",
                    "description": "Ticket markdown description.",
                },
                "provider": {
                    "type": "string",
                    "enum": ["linear", "jira"],
                    "description": "Ticket provider ('linear' or 'jira', default: 'linear').",
                },
            },
            "required": ["repo_root", "ticket_id", "title", "description"],
        },
    },
    {
        "name": "pmcursor_release_notes",
        "description": (
            "Generate release notes and PRD scope coverage from a unified git diff "
            "and indexed repository."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_root": {
                    "type": "string",
                    "description": "Path to the repository root directory.",
                },
                "prd_markdown": {
                    "type": "string",
                    "description": "PRD markdown content.",
                },
                "diff_text": {
                    "type": "string",
                    "description": "Unified git diff text.",
                },
                "prd_path": {
                    "type": "string",
                    "description": "Optional logical path label for the PRD (default: PRD.md).",
                },
                "version": {
                    "type": "string",
                    "description": "Release version label (default: Unreleased).",
                },
            },
            "required": ["repo_root", "prd_markdown", "diff_text"],
        },
    },
    {
        "name": "pmcursor_flags",
        "description": (
            "Audit PRD feature-flag declarations and rollout/rollback readiness against a repository."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prd_markdown": {
                    "type": "string",
                    "description": "PRD markdown content to audit for feature flags.",
                },
                "repo_root": {
                    "type": "string",
                    "description": "Path to the repository root directory (default: '.').",
                },
            },
            "required": ["prd_markdown"],
        },
    },
    {
        "name": "pmcursor_telemetry_verify",
        "description": (
            "Verify observed runtime telemetry event samples against indexed TelemetryContract definitions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Observed telemetry event samples with event_name and properties.",
                },
                "repo_root": {
                    "type": "string",
                    "description": "Path to the repository root directory (default: '.').",
                },
            },
            "required": ["events"],
        },
    },
]

_TOOL_REQUIRED_ARGS: dict[str, tuple[str, ...]] = {
    "pmcursor_index": ("repo_root",),
    "pmcursor_drift": ("repo_root", "prd_markdown"),
    "pmcursor_checklist": ("repo_root",),
    "pmcursor_ticket_sync": ("repo_root", "ticket_id", "title", "description"),
    "pmcursor_release_notes": ("repo_root", "prd_markdown", "diff_text"),
    "pmcursor_flags": ("prd_markdown",),
    "pmcursor_telemetry_verify": ("events",),
}


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _require_str_arg(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        raise TypeError(f"Argument '{key}' must be a string")
    return value


def _optional_str_arg(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"Argument '{key}' must be a string when provided")
    return value


class RepoIndexCache:
    """Bounded LRU in-memory RepoMap cache keyed by resolved path and file fingerprint."""

    def __init__(self, *, max_entries: int = 64) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._entries: OrderedDict[Path, tuple[RepoFingerprint, RepoMap]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._lock = threading.RLock()

    @property
    def max_entries(self) -> int:
        """Return the maximum number of cached repository entries."""
        return self._max_entries

    @property
    def size(self) -> int:
        """Return the number of cached repository entries."""
        with self._lock:
            return len(self._entries)

    @property
    def hits(self) -> int:
        """Return the number of cache hits."""
        with self._lock:
            return self._hits

    @property
    def misses(self) -> int:
        """Return the number of cache misses."""
        with self._lock:
            return self._misses

    def clear(self) -> None:
        """Remove all cached repository entries."""
        with self._lock:
            self._entries.clear()

    @staticmethod
    def _compute_fingerprint(repo_root: Path) -> RepoFingerprint:
        resolved_root = repo_root.resolve()
        records: list[FileFingerprint] = []

        for dirpath, dirnames, filenames in os.walk(resolved_root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            dir_path = Path(dirpath)
            for filename in filenames:
                file_path = dir_path / filename
                if file_path.is_symlink() or not file_path.is_file():
                    continue
                try:
                    stat_res = file_path.stat()
                except OSError:
                    continue
                rel_posix = file_path.relative_to(resolved_root).as_posix()
                records.append((rel_posix, stat_res.st_mtime_ns, stat_res.st_size))

        records.sort(key=lambda item: item[0])
        return tuple(records)

    def get_or_index(self, repo_root: Path) -> RepoMap:
        """Return a cached RepoMap when the repo fingerprint matches, else re-index."""
        resolved_root = repo_root.resolve()
        with self._lock:
            fingerprint = self._compute_fingerprint(resolved_root)
            cached = self._entries.get(resolved_root)
            if cached is not None and cached[0] == fingerprint:
                self._entries.move_to_end(resolved_root)
                self._hits += 1
                return cached[1]

            self._misses += 1
            repo_map = index_repository(resolved_root)
            self._entries[resolved_root] = (fingerprint, repo_map)
            self._entries.move_to_end(resolved_root)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return repo_map


class PMCursorMCPServer:
    """JSON-RPC 2.0 MCP server exposing PMCursor indexing and audit tools."""

    def __init__(
        self,
        *,
        allowed_workspace_root: Path | None = None,
        cache: RepoIndexCache | None = None,
    ) -> None:
        self._allowed_workspace_root = (
            allowed_workspace_root.resolve() if allowed_workspace_root is not None else None
        )
        self._cache = cache if cache is not None else RepoIndexCache()

    def _resolve_repo(self, raw_repo_root: str) -> Path:
        if not raw_repo_root or not raw_repo_root.strip():
            raise ValueError("repo_root must be a non-empty path")

        resolved = Path(raw_repo_root).expanduser().resolve()
        if (
            self._allowed_workspace_root is not None
            and not resolved.is_relative_to(self._allowed_workspace_root)
        ):
            raise PermissionError(
                f"Repository path '{resolved}' escapes allowed workspace root "
                f"'{self._allowed_workspace_root}'"
            )
        if not resolved.is_dir():
            raise FileNotFoundError(f"Repository directory not found: {resolved}")
        return resolved

    def _dispatch_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name in {"pmcursor_flags", "pmcursor_telemetry_verify"}:
            raw_repo_root = _optional_str_arg(arguments, "repo_root")
            if raw_repo_root is None:
                raw_repo_root = "."
        else:
            raw_repo_root = _require_str_arg(arguments, "repo_root")

        resolved_root = self._resolve_repo(raw_repo_root)

        if tool_name == "pmcursor_flags":
            prd_markdown = _require_str_arg(arguments, "prd_markdown")
            flag_report = audit_feature_flags_and_rollout(prd_markdown, resolved_root)
            return flag_report.model_dump(mode="json")

        repo_map = self._cache.get_or_index(resolved_root)

        if tool_name == "pmcursor_index":
            return repo_map.model_dump(mode="json")

        if tool_name == "pmcursor_drift":
            prd_markdown = _require_str_arg(arguments, "prd_markdown")
            prd_path = _optional_str_arg(arguments, "prd_path") or "PRD.md"
            drift_report = check_spec_drift(
                prd_markdown,
                repo_map,
                prd_path=prd_path,
                repo_root=resolved_root,
            )
            return drift_report.model_dump(mode="json")

        if tool_name == "pmcursor_checklist":
            optional_prd_markdown = _optional_str_arg(arguments, "prd_markdown")
            checklist = generate_edge_case_checklist(
                repo_map,
                prd_markdown=optional_prd_markdown,
                repo_root=resolved_root,
            )
            return checklist.model_dump(mode="json")

        if tool_name == "pmcursor_ticket_sync":
            ticket_id = _require_str_arg(arguments, "ticket_id")
            title = _require_str_arg(arguments, "title")
            description = _require_str_arg(arguments, "description")
            raw_provider = _optional_str_arg(arguments, "provider") or "linear"
            provider: TicketProvider
            if raw_provider == "linear":
                provider = "linear"
            elif raw_provider == "jira":
                provider = "jira"
            else:
                raise ValueError(f"Unsupported ticket provider: {raw_provider}")

            ticket_report = audit_ticket_against_repo(
                ticket_id,
                title,
                description,
                repo_map,
                provider=provider,
                repo_root=resolved_root,
            )
            return ticket_report.model_dump(mode="json")

        if tool_name == "pmcursor_release_notes":
            prd_markdown = _require_str_arg(arguments, "prd_markdown")
            diff_text = _require_str_arg(arguments, "diff_text")
            prd_path = _optional_str_arg(arguments, "prd_path") or "PRD.md"
            version = _optional_str_arg(arguments, "version") or "Unreleased"
            release_report = generate_release_notes_and_coverage(
                prd_markdown,
                diff_text,
                repo_map,
                prd_path=prd_path,
                version=version,
                repo_root=resolved_root,
            )
            return release_report.model_dump(mode="json")

        if tool_name == "pmcursor_telemetry_verify":
            raw_events = arguments.get("events")
            if not isinstance(raw_events, list) or not all(
                isinstance(item, dict) for item in raw_events
            ):
                raise TypeError("Argument 'events' must be a list of objects")
            telemetry_report = verify_telemetry_samples(repo_map, raw_events)
            return telemetry_report.model_dump(mode="json")

        raise ValueError(f"Unknown tool: {tool_name}")

    def _handle_tools_call(
        self,
        request_id: Any,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or tool_name not in _TOOL_REQUIRED_ARGS:
            return _jsonrpc_error(request_id, -32602, f"Unknown tool: {tool_name!r}")

        raw_arguments = params.get("arguments")
        if raw_arguments is None:
            arguments: dict[str, Any] = {}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            return _jsonrpc_error(
                request_id,
                -32602,
                "Invalid params: 'arguments' must be an object",
            )

        required_keys = _TOOL_REQUIRED_ARGS[tool_name]
        missing = [key for key in required_keys if key not in arguments or arguments[key] is None]
        if missing:
            return _jsonrpc_error(
                request_id,
                -32602,
                f"Invalid params: missing required argument(s): {', '.join(missing)}",
            )

        try:
            payload = self._dispatch_tool(tool_name, arguments)
        except (PermissionError, FileNotFoundError, ValueError, TypeError) as exc:
            error_payload = json.dumps(
                {"error": str(exc), "error_type": type(exc).__name__}
            )
            return _jsonrpc_result(
                request_id,
                {
                    "content": [{"type": "text", "text": error_payload}],
                    "isError": True,
                },
            )

        return _jsonrpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(payload)}],
                "isError": False,
            },
        )

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a single JSON-RPC 2.0 request dict; return None for notifications."""
        method = request.get("method")
        if "id" not in request or (
            isinstance(method, str) and method.startswith("notifications/")
        ):
            return None

        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _jsonrpc_error(request_id, -32600, "Invalid Request")

        raw_params = request.get("params")
        if raw_params is None:
            params: dict[str, Any] = {}
        elif isinstance(raw_params, dict):
            params = raw_params
        else:
            return _jsonrpc_error(request_id, -32602, "Invalid params: expected object")

        if method == "initialize":
            return _jsonrpc_result(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            )

        if method == "ping":
            return _jsonrpc_result(request_id, {})

        if method == "tools/list":
            return _jsonrpc_result(request_id, {"tools": _TOOL_DEFINITIONS})

        if method == "tools/call":
            return self._handle_tools_call(request_id, params)

        return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


def run_mcp_server(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    allowed_workspace_root: Path | None = None,
) -> None:
    """Run the line-delimited JSON-RPC 2.0 MCP server over stdio."""
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout
    server = PMCursorMCPServer(allowed_workspace_root=allowed_workspace_root)

    for raw_line in in_stream:
        line = raw_line.strip()
        if not line:
            continue

        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            error_response = _jsonrpc_error(None, -32700, f"Parse error: {exc.msg}")
            out_stream.write(json.dumps(error_response) + "\n")
            out_stream.flush()
            continue

        if not isinstance(parsed, dict):
            error_response = _jsonrpc_error(
                None,
                -32600,
                "Invalid Request: expected JSON object",
            )
            out_stream.write(json.dumps(error_response) + "\n")
            out_stream.flush()
            continue

        response = server.handle_request(parsed)
        if response is not None:
            out_stream.write(json.dumps(response) + "\n")
            out_stream.flush()
