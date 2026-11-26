from __future__ import annotations

import argparse
from pathlib import Path

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
