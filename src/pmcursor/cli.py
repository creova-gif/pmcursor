from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from api import OrgDashboardSummary, compute_pr_impact
from pmcursor.checklists import generate_edge_case_checklist
from pmcursor.drift import (
    check_spec_drift,
    fix_prd_markdown,
    format_drift_report_markdown,
)
from pmcursor.eval_runner import run_eval_benchmark
from pmcursor.feature_flags import (
    audit_feature_flags_and_rollout,
    extract_feature_flags,
)
from pmcursor.federation import index_federated_repos
from pmcursor.indexer import index_repository
from pmcursor.mcp_server import run_mcp_server
from pmcursor.plugin_validator import validate_plugin_manifests
from pmcursor.publisher import (
    PublishResult,
    publish_github_pr_comment,
    publish_jira_comment,
    publish_linear_comment,
)
from pmcursor.release_notes import (
    compute_scope_coverage,
    generate_release_notes_and_coverage,
)
from pmcursor.sarif import drift_report_to_sarif
from pmcursor.telemetry_verify import verify_telemetry_samples
from pmcursor.tickets import audit_ticket_against_repo
from web.canvas import render_split_pane_canvas

_run_server: Callable[..., None] | None
try:
    from api.server import run_server as _run_server
except ModuleNotFoundError:
    _run_server = None

CLI_EPILOG = """Examples:
  python3 -m pmcursor.cli index --repo . --json
  python3 -m pmcursor.cli drift --prd PROJECT_SPEC.md --repo . --md
  python3 -m pmcursor.cli fix-prd --prd PROJECT_SPEC.md --repo . --dry-run
  python3 -m pmcursor.cli pr-impact --prd PROJECT_SPEC.md --repo . --base main
  python3 -m pmcursor.cli canvas --prd PROJECT_SPEC.md --repo . --output canvas.html
  python3 -m pmcursor.cli checklist --repo . --prd PROJECT_SPEC.md --output checklist.md
  python3 -m pmcursor.cli ticket-sync --id ENG-42 --title "Add auth" --body-file ticket.md --repo .
  python3 -m pmcursor.cli serve --host 127.0.0.1 --port 8000
  python3 -m pmcursor.cli mcp
  python3 -m pmcursor.cli validate-plugin --repo .
  python3 -m pmcursor.cli doctor --repo .
  python3 -m pmcursor.cli eval --json
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmcursor",
        description="PMCursor: Codebase-aware contract indexer and PRD drift verifier for Product Managers.",
        epilog=CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser(
        "index",
        help="Index Pydantic, Zod, OpenAPI, SQL, telemetry, and ADR contracts into a JSON RepoMap.",
        epilog="Examples:\n  python3 -m pmcursor.cli index --repo . --json\n  python3 -m pmcursor.cli index --repo . --output repo_map.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    index_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory to index (default: .)",
    )
    index_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path to write the JSON RepoMap",
    )
    index_parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON RepoMap to stdout",
    )

    drift_parser = subparsers.add_parser(
        "drift",
        help="Check a PRD or spec markdown file for schema/route/telemetry drift and fabricated file:line citations.",
        epilog="Examples:\n  python3 -m pmcursor.cli drift --prd PROJECT_SPEC.md --repo . --md\n  python3 -m pmcursor.cli drift --prd PROJECT_SPEC.md --repo . --json --fail-on-drift",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    drift_parser.add_argument(
        "--prd",
        type=Path,
        required=True,
        help="Path to the PRD or markdown specification file",
    )
    drift_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    drift_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )
    drift_parser.add_argument(
        "--md",
        action="store_true",
        help="Emit formatted Markdown report (default)",
    )
    drift_parser.add_argument(
        "--sarif",
        action="store_true",
        help="Print SARIF 2.1.0 JSON report to stdout",
    )
    drift_parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit with code 1 if any drift finding or fabricated citation is detected",
    )

    fix_parser = subparsers.add_parser(
        "fix-prd",
        help="Repair shifted file:line citations and mismatched Model.field types in a PRD.",
        epilog="Examples:\n  python3 -m pmcursor.cli fix-prd --prd PRD.md --repo . --dry-run\n  python3 -m pmcursor.cli fix-prd --prd PRD.md --repo . --write --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fix_parser.add_argument(
        "--prd",
        type=Path,
        required=True,
        help="Path to the PRD markdown file",
    )
    fix_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    fix_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview repairs without modifying the PRD file (default)",
    )
    fix_parser.add_argument(
        "--write",
        action="store_true",
        help="Write repaired markdown back to --prd",
    )
    fix_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON FixPrdResult",
    )

    impact_parser = subparsers.add_parser(
        "pr-impact",
        help="Map a unified git diff to impacted RepoMap contracts and PRD references.",
        epilog="Examples:\n  python3 -m pmcursor.cli pr-impact --prd PRD.md --repo . --base main\n  python3 -m pmcursor.cli pr-impact --prd PRD.md --repo . --diff pr.diff --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    impact_parser.add_argument(
        "--prd",
        type=Path,
        required=True,
        help="Path to the PRD markdown file",
    )
    impact_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    impact_parser.add_argument(
        "--diff",
        type=Path,
        default=None,
        help="Path to a unified diff file (defaults to `git diff <base>...HEAD`)",
    )
    impact_parser.add_argument(
        "--base",
        type=str,
        default="main",
        help="Base git ref for diff calculation when --diff is omitted (default: main)",
    )
    impact_parser.add_argument(
        "--org-id",
        type=str,
        default="default",
        help="Tenant organization identifier (default: default)",
    )
    impact_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON PRImpactReport",
    )
    impact_parser.add_argument(
        "--md",
        action="store_true",
        help="Emit GitHub PR Markdown comment (default)",
    )

    canvas_parser = subparsers.add_parser(
        "canvas",
        help="Generate an interactive split-pane HTML spec-vs-code canvas.",
        epilog="Examples:\n  python3 -m pmcursor.cli canvas --prd PRD.md --repo . --output canvas.html",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    canvas_parser.add_argument(
        "--prd",
        type=Path,
        required=True,
        help="Path to the PRD markdown file",
    )
    canvas_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    canvas_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output HTML file path",
    )
    canvas_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON summary of generated canvas",
    )

    checklist_parser = subparsers.add_parser(
        "checklist",
        help="Generate a RepoMap-backed edge-case and test checklist.",
        epilog="Examples:\n  python3 -m pmcursor.cli checklist --repo .\n  python3 -m pmcursor.cli checklist --repo . --prd PROJECT_SPEC.md --output checklist.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    checklist_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    checklist_parser.add_argument(
        "--prd",
        type=Path,
        default=None,
        help="Optional path to a PRD markdown file for tailored edge cases",
    )
    checklist_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path to write the checklist output",
    )
    checklist_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON EdgeCaseChecklist",
    )

    plugin_parser = subparsers.add_parser(
        "validate-plugin",
        help="Validate .cursor-plugin/plugin.json and .claude-plugin/plugin.json manifests and components.",
        epilog="Examples:\n  python3 -m pmcursor.cli validate-plugin --repo .\n  python3 -m pmcursor.cli validate-plugin --repo . --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    plugin_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root containing .cursor-plugin/plugin.json (default: .)",
    )
    plugin_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON validation result",
    )

    eval_parser = subparsers.add_parser(
        "eval",
        help="Run deterministic evaluation benchmark (verifying 0 fabricated paths and >=85%% drift recall).",
        epilog="Examples:\n  python3 -m pmcursor.cli eval --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    eval_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON evaluation result",
    )

    ticket_parser = subparsers.add_parser(
        "ticket-sync",
        help="Audit a Linear or Jira ticket body against RepoMap contracts.",
        epilog="Examples:\n  python3 -m pmcursor.cli ticket-sync --id ENG-42 --title \"Add auth\" --body-file ticket.md --repo .",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ticket_parser.add_argument(
        "--id",
        type=str,
        required=True,
        help="Ticket identifier (e.g. ENG-42)",
    )
    ticket_parser.add_argument(
        "--title",
        type=str,
        required=True,
        help="Ticket title",
    )
    ticket_parser.add_argument(
        "--body-file",
        type=Path,
        required=True,
        help="Path to the markdown file containing the ticket description",
    )
    ticket_parser.add_argument(
        "--provider",
        choices=["linear", "jira"],
        default="linear",
        help="Ticket provider (default: linear)",
    )
    ticket_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    ticket_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON TicketSyncReport",
    )
    ticket_parser.add_argument(
        "--md",
        action="store_true",
        help="Emit formatted Markdown ticket comment (default)",
    )
    ticket_parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit with code 1 if any drift finding or fabricated citation is detected",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the PMCursor FastAPI server.",
        epilog="Examples:\n  python3 -m pmcursor.cli serve --host 127.0.0.1 --port 8000",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    serve_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Bind host address (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind port number (default: 8000)",
    )

    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Start the PMCursor stdio MCP server.",
        epilog="Examples:\n  python3 -m pmcursor.cli mcp\n  python3 -m pmcursor.cli mcp --workspace-root .",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mcp_parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Optional workspace root directory to confine MCP tool repo_root arguments",
    )

    release_notes_parser = subparsers.add_parser(
        "release-notes",
        help="Generate release notes and PRD scope coverage from a git diff or diff file.",
        epilog="Examples:\n  python3 -m pmcursor.cli release-notes --prd PRD.md --repo . --base HEAD~1\n  python3 -m pmcursor.cli release-notes --prd PRD.md --repo . --diff-file pr.diff --version v1.2.0 --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    release_notes_parser.add_argument(
        "--prd",
        type=Path,
        required=True,
        help="Path to the PRD markdown file",
    )
    release_notes_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    release_notes_parser.add_argument(
        "--base",
        type=str,
        default="HEAD~1",
        help="Base git ref for diff calculation when --diff-file is omitted (default: HEAD~1)",
    )
    release_notes_parser.add_argument(
        "--diff-file",
        type=Path,
        default=None,
        help="Path to a unified diff file (defaults to `git diff <base>...HEAD`)",
    )
    release_notes_parser.add_argument(
        "--version",
        type=str,
        default="Unreleased",
        help="Release version label (default: Unreleased)",
    )
    release_notes_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path to write the release notes report",
    )
    release_notes_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON ReleaseNotesReport",
    )

    flags_parser = subparsers.add_parser(
        "flags",
        help="Extract feature flags or audit PRD flag & rollback coverage against a repository.",
        epilog="Examples:\n  python3 -m pmcursor.cli flags --repo . --json\n  python3 -m pmcursor.cli flags --repo . --prd PROJECT_SPEC.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    flags_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    flags_parser.add_argument(
        "--prd",
        type=Path,
        default=None,
        help="Optional path to a PRD markdown file for rollout & flag audit",
    )
    flags_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    federate_parser = subparsers.add_parser(
        "federate",
        help="Index and merge multiple repositories under alias=path prefixes, optionally checking PRD drift.",
        epilog="Examples:\n  python3 -m pmcursor.cli federate --repos api=./backend web=./frontend --json\n  python3 -m pmcursor.cli federate --repos api=./backend web=./frontend --prd SPEC.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    federate_parser.add_argument(
        "--repos",
        nargs="+",
        required=True,
        help="List of alias=path repository entries",
    )
    federate_parser.add_argument(
        "--prd",
        type=Path,
        default=None,
        help="Optional path to a PRD markdown file to run drift checks against the federated RepoMap",
    )
    federate_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    telemetry_parser = subparsers.add_parser(
        "telemetry-verify",
        help="Verify observed runtime telemetry samples against indexed TelemetryContract definitions.",
        epilog="Examples:\n  python3 -m pmcursor.cli telemetry-verify --repo . --events-file events.json\n  python3 -m pmcursor.cli telemetry-verify --repo . --events-file events.ndjson --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    telemetry_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    telemetry_parser.add_argument(
        "--events-file",
        type=Path,
        required=True,
        help="Path to a JSON array or NDJSON file of observed telemetry events",
    )
    telemetry_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON TelemetryVerificationReport",
    )

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Compute an organization alignment summary across contracts, flags, drift, coverage, and checklist.",
        epilog="Examples:\n  python3 -m pmcursor.cli dashboard --repo . --prd PROJECT_SPEC.md\n  python3 -m pmcursor.cli dashboard --repo . --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    dashboard_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: .)",
    )
    dashboard_parser.add_argument(
        "--prd",
        type=Path,
        default=Path("PROJECT_SPEC.md"),
        help="Path to the PRD markdown file (default: PROJECT_SPEC.md)",
    )
    dashboard_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON OrgDashboardSummary",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run environment, plugin, and configuration diagnostics.",
        epilog="Examples:\n  python3 -m pmcursor.cli doctor --repo .\n  python3 -m pmcursor.cli doctor --repo . --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor_parser.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository root directory to inspect (default: .)",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON diagnostic report",
    )

    publish_parser = subparsers.add_parser(
        "publish",
        help="Publish a comment to a GitHub PR, Linear issue, or Jira issue.",
        epilog=(
            "Examples:\n"
            "  python3 -m pmcursor.cli publish --provider github --target owner/repo#42 --body-file comment.md --dry-run\n"
            "  python3 -m pmcursor.cli publish --provider linear --target ENG-42 --body-file comment.md --json\n"
            "  python3 -m pmcursor.cli publish --provider jira --target ENG-42 --jira-base-url https://jira.example.com --body-file comment.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    publish_parser.add_argument(
        "--provider",
        choices=["github", "linear", "jira"],
        required=True,
        help="Target issue/PR provider",
    )
    publish_parser.add_argument(
        "--target",
        type=str,
        required=True,
        help="Target identifier (owner/repo#42 for github, ISSUE-ID for linear/jira)",
    )
    publish_parser.add_argument(
        "--body-file",
        type=Path,
        required=True,
        help="Path to markdown/text file containing the comment body",
    )
    publish_parser.add_argument(
        "--jira-base-url",
        type=str,
        default=None,
        help="Jira base URL (or set PMCURSOR_JIRA_BASE_URL)",
    )
    publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and build payload without sending an HTTP request",
    )
    publish_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON PublishResult",
    )

    return parser


def _require_prd_and_repo(prd_path: Path, repo_path: Path, example_cmd: str) -> bool:
    if not prd_path.is_file():
        print(
            f"Error: PRD file '{prd_path}' not found.\n  Try: {example_cmd}",
            file=sys.stderr,
        )
        return False
    if not repo_path.is_dir():
        print(
            f"Error: Repository directory '{repo_path}' does not exist.\n  Try: {example_cmd}",
            file=sys.stderr,
        )
        return False
    return True


def _load_diff_text(diff_path: Path | None, repo_path: Path, base_ref: str) -> str:
    if diff_path is not None:
        return diff_path.read_text(encoding="utf-8")
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "diff", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _load_telemetry_events(events_file: Path) -> list[dict[str, Any]]:
    raw_text = events_file.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    if raw_text.startswith("["):
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
            raise ValueError("JSON events file must contain a list of event objects.")
        return parsed
    events: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        item = json.loads(stripped)
        if not isinstance(item, dict):
            raise TypeError("Each NDJSON line must be a JSON object.")
        events.append(item)
    return events


def _run_doctor(repo_path: Path, *, emit_json: bool) -> int:
    """Collect and print environment, plugin, and secret-presence diagnostics."""
    if not repo_path.is_dir():
        print(
            f"Error: Repository directory '{repo_path}' does not exist.\n"
            "  Try: python3 -m pmcursor.cli doctor --repo .",
            file=sys.stderr,
        )
        return 2

    plugin_valid = validate_plugin_manifests(repo_path).valid
    checks: dict[str, str | bool] = {
        "python_version": platform.python_version(),
        "server_extra_available": _run_server is not None,
        "plugin_valid": plugin_valid,
        "api_token_configured": bool(os.environ.get("PMCURSOR_API_TOKEN", "").strip()),
        "github_webhook_secret_configured": bool(
            os.environ.get("PMCURSOR_WEBHOOK_SECRET", "").strip()
        ),
        "linear_webhook_secret_configured": bool(
            os.environ.get("PMCURSOR_LINEAR_WEBHOOK_SECRET", "").strip()
        ),
        "jira_webhook_secret_configured": bool(
            os.environ.get("PMCURSOR_JIRA_WEBHOOK_SECRET", "").strip()
        ),
    }

    if emit_json:
        print(json.dumps(checks, indent=2))
    else:
        rows = [
            ("python_version", str(checks["python_version"])),
            (
                "server_extra_available",
                "available" if checks["server_extra_available"] else "unavailable",
            ),
            ("plugin_valid", "valid" if checks["plugin_valid"] else "invalid"),
            (
                "api_token_configured",
                "configured" if checks["api_token_configured"] else "unset",
            ),
            (
                "github_webhook_secret_configured",
                "configured" if checks["github_webhook_secret_configured"] else "unset",
            ),
            (
                "linear_webhook_secret_configured",
                "configured" if checks["linear_webhook_secret_configured"] else "unset",
            ),
            (
                "jira_webhook_secret_configured",
                "configured" if checks["jira_webhook_secret_configured"] else "unset",
            ),
        ]
        width = max(len(key) for key, _ in rows)
        print("PMCursor Doctor")
        for key, value in rows:
            print(f"  {key:<{width}} : {value}")

    return 0 if plugin_valid else 1


def _parse_github_pr_target(target: str) -> tuple[str, int]:
    """Parse a GitHub PR target formatted as 'owner/repo#pr_number'."""
    repo_part, sep, pr_part = target.partition("#")
    owner, slash, repo = repo_part.partition("/")
    if not sep or not slash or not owner.strip() or not repo.strip() or not pr_part.strip():
        raise ValueError(
            f"Invalid GitHub target '{target}'. Expected format 'owner/repo#pr_number'."
        )
    try:
        pr_number = int(pr_part)
    except ValueError as exc:
        raise ValueError(
            f"Invalid GitHub PR number in target '{target}': '{pr_part}' is not an integer."
        ) from exc
    if pr_number <= 0:
        raise ValueError(
            f"Invalid GitHub PR number in target '{target}': must be a positive integer."
        )
    return repo_part, pr_number


def _run_publish(
    *,
    provider: str,
    target: str,
    body_file: Path,
    jira_base_url: str | None,
    dry_run: bool,
    emit_json: bool,
) -> int:
    """Publish a comment to GitHub, Linear, or Jira from a markdown/text body file."""
    if not body_file.is_file():
        print(f"Error: Body file '{body_file}' not found.", file=sys.stderr)
        return 2

    try:
        body = body_file.read_text(encoding="utf-8")
        result: PublishResult
        if provider == "github":
            repo_full_name, pr_number = _parse_github_pr_target(target)
            token = (
                None
                if dry_run
                else (os.environ.get("GITHUB_TOKEN") or os.environ.get("PMCURSOR_GITHUB_TOKEN"))
            )
            result = publish_github_pr_comment(
                repo_full_name,
                pr_number,
                body,
                token=token,
                dry_run=dry_run,
            )
        elif provider == "linear":
            api_key = (
                None
                if dry_run
                else (os.environ.get("LINEAR_API_KEY") or os.environ.get("PMCURSOR_LINEAR_API_KEY"))
            )
            result = publish_linear_comment(
                target,
                body,
                api_key=api_key,
                dry_run=dry_run,
            )
        elif provider == "jira":
            resolved_base_url = (jira_base_url or os.environ.get("PMCURSOR_JIRA_BASE_URL") or "").strip()
            if not resolved_base_url:
                print(
                    "Error: Missing Jira base URL. Pass --jira-base-url or set PMCURSOR_JIRA_BASE_URL.",
                    file=sys.stderr,
                )
                return 2
            bearer_token = (
                None
                if dry_run
                else (os.environ.get("JIRA_API_TOKEN") or os.environ.get("PMCURSOR_JIRA_API_TOKEN"))
            )
            result = publish_jira_comment(
                resolved_base_url,
                target,
                body,
                bearer_token=bearer_token,
                dry_run=dry_run,
            )
        else:
            print(f"Error: Unsupported publish provider '{provider}'.", file=sys.stderr)
            return 2
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if emit_json:
        print(result.model_dump_json(indent=2))
    else:
        mode = "dry-run" if result.dry_run else "published"
        print(f"[{mode}] {result.provider} {result.target_id} -> {result.url} (status={result.status_code})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "index":
        repo_path: Path = args.repo
        if not repo_path.is_dir():
            print(
                f"Error: Repository directory '{repo_path}' does not exist.\n"
                "  Try: python3 -m pmcursor.cli index --repo . --json",
                file=sys.stderr,
            )
            return 2
        repo_map = index_repository(repo_path)
        payload = repo_map.model_dump_json(indent=2)
        if args.output is not None:
            args.output.write_text(payload + "\n", encoding="utf-8")
        if args.json or args.output is None:
            print(payload)
        return 0

    if args.command == "drift":
        prd_path: Path = args.prd
        repo_path = args.repo
        if not _require_prd_and_repo(
            prd_path,
            repo_path,
            "python3 -m pmcursor.cli drift --prd PROJECT_SPEC.md --repo . --md",
        ):
            return 2

        prd_md = prd_path.read_text(encoding="utf-8")
        repo_map = index_repository(repo_path)
        report = check_spec_drift(
            prd_md,
            repo_map,
            prd_path=prd_path.as_posix(),
            repo_root=repo_path.resolve(),
        )
        if args.sarif:
            print(json.dumps(drift_report_to_sarif(report), indent=2))
        elif args.json:
            print(report.model_dump_json(indent=2))
        else:
            print(format_drift_report_markdown(report), end="")

        if args.fail_on_drift and report.findings:
            return 1
        return 0

    if args.command == "fix-prd":
        prd_path = args.prd
        repo_path = args.repo
        if not _require_prd_and_repo(
            prd_path,
            repo_path,
            "python3 -m pmcursor.cli fix-prd --prd PRD.md --repo . --dry-run",
        ):
            return 2

        prd_md = prd_path.read_text(encoding="utf-8")
        repo_map = index_repository(repo_path)
        result = fix_prd_markdown(
            prd_md,
            repo_map,
            prd_path=prd_path.as_posix(),
            repo_root=repo_path.resolve(),
        )
        should_write = bool(args.write and not args.dry_run)
        if should_write:
            prd_path.write_text(result.updated_markdown, encoding="utf-8")
            result = result.model_copy(update={"applied": True})

        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            print(result.updated_markdown, end="")
        return 0

    if args.command == "pr-impact":
        prd_path = args.prd
        repo_path = args.repo
        if not _require_prd_and_repo(
            prd_path,
            repo_path,
            "python3 -m pmcursor.cli pr-impact --prd PROJECT_SPEC.md --repo . --base main",
        ):
            return 2
        if args.diff is not None and not args.diff.is_file():
            print(
                f"Error: Diff file '{args.diff}' not found.\n"
                "  Try: python3 -m pmcursor.cli pr-impact --prd PROJECT_SPEC.md --repo . --base main",
                file=sys.stderr,
            )
            return 2

        prd_md = prd_path.read_text(encoding="utf-8")
        diff_text = _load_diff_text(args.diff, repo_path.resolve(), args.base)
        repo_map = index_repository(repo_path)
        impact = compute_pr_impact(
            prd_md,
            diff_text,
            repo_map,
            prd_path=prd_path.as_posix(),
            org_id=args.org_id,
        )
        if args.json:
            print(impact.model_dump_json(indent=2))
        else:
            print(impact.markdown_comment, end="")
        return 0

    if args.command == "canvas":
        prd_path = args.prd
        repo_path = args.repo
        if not _require_prd_and_repo(
            prd_path,
            repo_path,
            "python3 -m pmcursor.cli canvas --prd PROJECT_SPEC.md --repo . --output canvas.html",
        ):
            return 2

        prd_md = prd_path.read_text(encoding="utf-8")
        repo_map = index_repository(repo_path)
        report = check_spec_drift(
            prd_md,
            repo_map,
            prd_path=prd_path.as_posix(),
            repo_root=repo_path.resolve(),
        )
        html_doc = render_split_pane_canvas(prd_md, repo_map, report)
        output_path: Path = args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_doc, encoding="utf-8")
        if args.json:
            print(
                f'{{"output": "{output_path.as_posix()}", "status": "{report.status}", '
                f'"overall_score": {report.alignment_score.overall_score}}}'
            )
        else:
            print(f"Canvas written to {output_path.as_posix()} (score: {report.alignment_score.overall_score}/100)")
        return 0

    if args.command == "checklist":
        repo_path = args.repo
        if not repo_path.is_dir():
            print(
                f"Error: Repository directory '{repo_path}' does not exist.\n"
                "  Try: python3 -m pmcursor.cli checklist --repo .",
                file=sys.stderr,
            )
            return 2
        prd_md_opt: str | None = None
        if args.prd is not None:
            prd_path = args.prd
            if not prd_path.is_file():
                print(
                    f"Error: PRD file '{prd_path}' not found.\n"
                    "  Try: python3 -m pmcursor.cli checklist --repo . --prd PROJECT_SPEC.md",
                    file=sys.stderr,
                )
                return 2
            prd_md_opt = prd_path.read_text(encoding="utf-8")

        repo_map = index_repository(repo_path)
        checklist = generate_edge_case_checklist(
            repo_map,
            prd_markdown=prd_md_opt,
            repo_root=repo_path.resolve(),
        )
        output_text = checklist.model_dump_json(indent=2) if args.json else checklist.markdown
        if args.output is not None:
            output_path = args.output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            content = output_text if output_text.endswith("\n") else output_text + "\n"
            output_path.write_text(content, encoding="utf-8")
        else:
            print(output_text, end="" if output_text.endswith("\n") else "\n")
        return 0

    if args.command == "validate-plugin":
        validation_result = validate_plugin_manifests(args.repo)
        if args.json:
            print(validation_result.model_dump_json(indent=2))
        else:
            status_str = "VALID" if validation_result.valid else "INVALID"
            print(
                f"Plugin: {validation_result.plugin_name} v{validation_result.version} [{status_str}] "
                f"({len(validation_result.checked_components)} components checked)"
            )
            for err in validation_result.errors:
                print(f"  ERROR: {err}", file=sys.stderr)
        return 0 if validation_result.valid else 1

    if args.command == "eval":
        bench = run_eval_benchmark()
        if args.json:
            print(bench.model_dump_json(indent=2))
        else:
            verdict = "PASS" if bench.passed else "FAIL"
            print(
                f"Eval Benchmark: {verdict} | Recall: {bench.recall * 100:.1f}% "
                f"({bench.detected_mismatches}/{bench.seeded_mismatches}) | "
                f"Fabricated Citations Caught: {bench.detected_fabricated_citations}/{bench.seeded_fabricated_citations} | "
                f"Unflagged Fabricated: {bench.unflagged_fabricated_citations}"
            )
        return 0 if bench.passed else 1

    if args.command == "ticket-sync":
        body_path: Path = args.body_file
        repo_path = args.repo
        if not body_path.is_file():
            print(
                f"Error: Ticket body file '{body_path}' not found.\n"
                "  Try: python3 -m pmcursor.cli ticket-sync --id ENG-42 --title \"Spec\" --body-file ticket.md --repo .",
                file=sys.stderr,
            )
            return 2
        if not repo_path.is_dir():
            print(
                f"Error: Repository directory '{repo_path}' does not exist.\n"
                "  Try: python3 -m pmcursor.cli ticket-sync --id ENG-42 --title \"Spec\" --body-file ticket.md --repo .",
                file=sys.stderr,
            )
            return 2

        description = body_path.read_text(encoding="utf-8")
        repo_map = index_repository(repo_path)
        sync_report = audit_ticket_against_repo(
            args.id,
            args.title,
            description,
            repo_map,
            provider=args.provider,
            repo_root=repo_path.resolve(),
        )
        if args.json:
            print(sync_report.model_dump_json(indent=2))
        else:
            print(sync_report.comment_markdown, end="")

        if args.fail_on_drift and sync_report.drift_report.findings:
            return 1
        return 0

    if args.command == "serve":
        if _run_server is None:
            print(
                "Error: server dependencies are not installed. "
                "Install with: pip install 'pmcursor[server]'",
                file=sys.stderr,
            )
            return 2
        try:
            _run_server(host=args.host, port=args.port)
        except (RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "mcp":
        run_mcp_server(allowed_workspace_root=args.workspace_root)
        return 0

    if args.command == "release-notes":
        prd_path = args.prd
        repo_path = args.repo
        if not _require_prd_and_repo(
            prd_path,
            repo_path,
            "python3 -m pmcursor.cli release-notes --prd PROJECT_SPEC.md --repo . --base HEAD~1",
        ):
            return 2
        if args.diff_file is not None and not args.diff_file.is_file():
            print(
                f"Error: Diff file '{args.diff_file}' not found.\n"
                "  Try: python3 -m pmcursor.cli release-notes --prd PROJECT_SPEC.md --repo . --base HEAD~1",
                file=sys.stderr,
            )
            return 2

        prd_md = prd_path.read_text(encoding="utf-8")
        resolved_repo = repo_path.resolve()
        diff_text = _load_diff_text(args.diff_file, resolved_repo, args.base)
        repo_map = index_repository(repo_path)
        release_report = generate_release_notes_and_coverage(
            prd_md,
            diff_text,
            repo_map,
            prd_path=prd_path.as_posix(),
            version=args.version,
            repo_root=resolved_repo,
        )
        output_text = (
            release_report.model_dump_json(indent=2)
            if args.json
            else release_report.markdown
        )
        if args.output is not None:
            output_path = args.output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            content = output_text if output_text.endswith("\n") else output_text + "\n"
            output_path.write_text(content, encoding="utf-8")
        else:
            print(output_text, end="" if output_text.endswith("\n") else "\n")
        return 0

    if args.command == "flags":
        repo_path = args.repo
        if not repo_path.is_dir():
            print(
                f"Error: Repository directory '{repo_path}' does not exist.\n"
                "  Try: python3 -m pmcursor.cli flags --repo . --json",
                file=sys.stderr,
            )
            return 2
        if args.prd is not None:
            prd_path = args.prd
            if not prd_path.is_file():
                print(
                    f"Error: PRD file '{prd_path}' not found.\n"
                    "  Try: python3 -m pmcursor.cli flags --repo . --prd PROJECT_SPEC.md",
                    file=sys.stderr,
                )
                return 2
            prd_md = prd_path.read_text(encoding="utf-8")
            flag_report = audit_feature_flags_and_rollout(prd_md, repo_path)
            if args.json:
                print(flag_report.model_dump_json(indent=2))
            else:
                print(
                    flag_report.markdown,
                    end="" if flag_report.markdown.endswith("\n") else "\n",
                )
            return 0

        flags = extract_feature_flags(repo_path)
        if args.json:
            print(json.dumps([f.model_dump() for f in flags], indent=2))
        elif not flags:
            print("No feature flags detected.")
        else:
            for flag in flags:
                print(f"{flag.flag_key} [{flag.provider}] ({flag.citation})")
        return 0

    if args.command == "federate":
        named_roots: list[tuple[str, Path]] = []
        for entry in args.repos:
            alias, sep, raw_path = entry.partition("=")
            clean_alias = alias.strip()
            clean_path = raw_path.strip()
            if not sep or not clean_alias or not clean_path:
                print(
                    f"Error: Invalid --repos entry '{entry}'. Expected alias=path.\n"
                    "  Try: python3 -m pmcursor.cli federate --repos api=./backend web=./frontend",
                    file=sys.stderr,
                )
                return 2
            root_dir = Path(clean_path)
            if not root_dir.is_dir():
                print(
                    f"Error: Repository directory '{root_dir}' for alias '{clean_alias}' does not exist.\n"
                    "  Try: python3 -m pmcursor.cli federate --repos api=./backend web=./frontend",
                    file=sys.stderr,
                )
                return 2
            named_roots.append((clean_alias, root_dir))

        federated_map = index_federated_repos(named_roots)
        if args.prd is not None:
            prd_path = args.prd
            if not prd_path.is_file():
                print(
                    f"Error: PRD file '{prd_path}' not found.\n"
                    "  Try: python3 -m pmcursor.cli federate --repos api=./backend --prd SPEC.md",
                    file=sys.stderr,
                )
                return 2
            prd_md = prd_path.read_text(encoding="utf-8")
            drift_report = check_spec_drift(
                prd_md,
                federated_map,
                prd_path=prd_path.as_posix(),
            )
            if args.json:
                print(drift_report.model_dump_json(indent=2))
            else:
                print(format_drift_report_markdown(drift_report), end="")
            return 0

        if args.json:
            print(federated_map.model_dump_json(indent=2))
        else:
            print(
                f"Federated RepoMap ({len(named_roots)} repos): "
                f"{len(federated_map.models)} models, "
                f"{len(federated_map.routes)} routes, "
                f"{len(federated_map.telemetry)} telemetry, "
                f"{len(federated_map.adrs)} ADRs"
            )
        return 0

    if args.command == "telemetry-verify":
        repo_path = args.repo
        events_file: Path = args.events_file
        if not repo_path.is_dir():
            print(
                f"Error: Repository directory '{repo_path}' does not exist.\n"
                "  Try: python3 -m pmcursor.cli telemetry-verify --repo . --events-file events.json",
                file=sys.stderr,
            )
            return 2
        if not events_file.is_file():
            print(
                f"Error: Events file '{events_file}' not found.\n"
                "  Try: python3 -m pmcursor.cli telemetry-verify --repo . --events-file events.json",
                file=sys.stderr,
            )
            return 2
        try:
            events = _load_telemetry_events(events_file)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"Error: Invalid telemetry events file '{events_file}': {exc}", file=sys.stderr)
            return 2
        repo_map = index_repository(repo_path)
        telemetry_report = verify_telemetry_samples(repo_map, events)
        if args.json:
            print(telemetry_report.model_dump_json(indent=2))
        else:
            print(
                telemetry_report.markdown,
                end="" if telemetry_report.markdown.endswith("\n") else "\n",
            )
        return 0

    if args.command == "dashboard":
        repo_path = args.repo
        if not repo_path.is_dir():
            print(
                f"Error: Repository directory '{repo_path}' does not exist.\n"
                "  Try: python3 -m pmcursor.cli dashboard --repo . --prd PROJECT_SPEC.md",
                file=sys.stderr,
            )
            return 2
        resolved_repo = repo_path.resolve()
        prd_arg: Path = args.prd
        if not prd_arg.is_absolute() and (resolved_repo / prd_arg).is_file():
            prd_md = (resolved_repo / prd_arg).read_text(encoding="utf-8")
            prd_label = prd_arg.as_posix()
        elif prd_arg.is_file():
            prd_md = prd_arg.read_text(encoding="utf-8")
            prd_label = prd_arg.as_posix()
        else:
            prd_md = ""
            prd_label = prd_arg.as_posix()

        repo_map = index_repository(repo_path)
        flags = extract_feature_flags(repo_path)
        drift_report = check_spec_drift(
            prd_md,
            repo_map,
            prd_path=prd_label,
            repo_root=resolved_repo,
        )
        scope_coverage = compute_scope_coverage(prd_md, repo_map)
        checklist = generate_edge_case_checklist(
            repo_map,
            prd_markdown=prd_md or None,
            repo_root=resolved_repo,
        )
        summary = OrgDashboardSummary(
            repo_root=repo_map.repo_root,
            models_count=len(repo_map.models),
            routes_count=len(repo_map.routes),
            telemetry_count=len(repo_map.telemetry),
            adrs_count=len(repo_map.adrs),
            feature_flags_count=len(flags),
            alignment_score=drift_report.alignment_score.overall_score,
            scope_coverage_percent=scope_coverage.coverage_percent,
            p0_checklist_items=checklist.p0_count,
            status=drift_report.status,
        )
        if args.json:
            print(summary.model_dump_json(indent=2))
        else:
            print(
                "\n".join(
                    [
                        "## PMCursor Org Alignment Dashboard",
                        f"- **Repo:** `{summary.repo_root}`",
                        (
                            f"- **Status:** `{summary.status}` "
                            f"(Alignment Score: **{summary.alignment_score}/100**, "
                            f"Scope Coverage: **{summary.scope_coverage_percent}%**)"
                        ),
                        (
                            f"- **Contracts:** {summary.models_count} models, "
                            f"{summary.routes_count} routes, "
                            f"{summary.telemetry_count} telemetry, "
                            f"{summary.adrs_count} ADRs, "
                            f"{summary.feature_flags_count} feature flags"
                        ),
                        f"- **P0 Checklist Items:** {summary.p0_checklist_items}",
                    ]
                )
            )
        return 0

    if args.command == "doctor":
        return _run_doctor(args.repo, emit_json=args.json)

    if args.command == "publish":
        return _run_publish(
            provider=args.provider,
            target=args.target,
            body_file=args.body_file,
            jira_base_url=args.jira_base_url,
            dry_run=args.dry_run,
            emit_json=args.json,
        )

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
