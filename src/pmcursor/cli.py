from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from api import compute_pr_impact
from api.server import run_server
from pmcursor.drift import (
    check_spec_drift,
    fix_prd_markdown,
    format_drift_report_markdown,
)
from pmcursor.eval_runner import run_eval_benchmark
from pmcursor.indexer import index_repository
from pmcursor.plugin_validator import validate_plugin_manifests
from pmcursor.tickets import audit_ticket_against_repo
from web.canvas import render_split_pane_canvas

CLI_EPILOG = """Examples:
  python3 -m pmcursor.cli index --repo . --json
  python3 -m pmcursor.cli drift --prd PROJECT_SPEC.md --repo . --md
  python3 -m pmcursor.cli fix-prd --prd PROJECT_SPEC.md --repo . --dry-run
  python3 -m pmcursor.cli pr-impact --prd PROJECT_SPEC.md --repo . --base main
  python3 -m pmcursor.cli canvas --prd PROJECT_SPEC.md --repo . --output canvas.html
  python3 -m pmcursor.cli ticket-sync --id ENG-42 --title "Add auth" --body-file ticket.md --repo .
  python3 -m pmcursor.cli serve --host 127.0.0.1 --port 8000
  python3 -m pmcursor.cli validate-plugin --repo .
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
        if args.json:
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
        run_server(host=args.host, port=args.port)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
