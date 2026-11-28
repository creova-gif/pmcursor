from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from api import OrgDashboardSummary, compute_pr_impact
from pmcursor._cli_parser import CLI_EPILOG, build_parser
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
from pmcursor.github_app import (
    GitHubAppError,
    build_app_manifest,
    default_github_app,
    exchange_manifest_code,
)
from pmcursor.indexer import index_repository
from pmcursor.llm import default_llm_client, summarize_drift_report
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
from pmcursor.telemetry_connectors import (
    ConnectorFetchError,
    fetch_telemetry_events,
)
from pmcursor.telemetry_verify import verify_telemetry_samples
from pmcursor.tenancy import (
    DEFAULT_STORE_PATH,
    ENV_ORG_STORE,
    OrgRegistry,
    OrgRegistryError,
)
from pmcursor.tickets import audit_ticket_against_repo
from web.canvas import render_split_pane_canvas

__all__ = ["CLI_EPILOG", "build_parser", "main"]

_run_server: Callable[..., None] | None
try:
    from api.server import run_server as _run_server
except ModuleNotFoundError:
    _run_server = None


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
    if base_ref.startswith("-"):
        raise ValueError(f"Invalid git base ref: {base_ref!r}")
    git_exe = shutil.which("git")
    if git_exe is None:
        return ""
    proc = subprocess.run(  # noqa: S603
        [git_exe, "-C", str(repo_path), "diff", f"{base_ref}...HEAD"],
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
        events_file: Path | None = args.events_file
        if not repo_path.is_dir():
            print(
                f"Error: Repository directory '{repo_path}' does not exist.\n"
                "  Try: python3 -m pmcursor.cli telemetry-verify --repo . --events-file events.json",
                file=sys.stderr,
            )
            return 2
        if (events_file is None) == (args.source is None):
            print(
                "Error: Provide exactly one of --events-file or --source.\n"
                "  Try: python3 -m pmcursor.cli telemetry-verify --repo . --source langfuse",
                file=sys.stderr,
            )
            return 2
        if events_file is not None and not events_file.is_file():
            print(
                f"Error: Events file '{events_file}' not found.\n"
                "  Try: python3 -m pmcursor.cli telemetry-verify --repo . --events-file events.json",
                file=sys.stderr,
            )
            return 2
        try:
            if events_file is not None:
                events = _load_telemetry_events(events_file)
            else:
                events = [
                    e.model_dump()
                    for e in fetch_telemetry_events(
                        args.source, limit=args.limit
                    ).events
                ]
        except ConnectorFetchError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
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

    if args.command == "github-app":
        try:
            if args.action == "manifest":
                if not args.webhook_url.strip():
                    print(
                        "Error: --webhook-url is required for the manifest action.\n"
                        "  Try: python3 -m pmcursor.cli github-app manifest --webhook-url https://pm.example.com/v1/webhooks/github",
                        file=sys.stderr,
                    )
                    return 2
                manifest = build_app_manifest(
                    name=args.name,
                    webhook_url=args.webhook_url,
                    redirect_url=args.redirect_url,
                    homepage_url=args.homepage_url,
                    public=args.public,
                )
                print(json.dumps(manifest, indent=2))
                return 0
            if args.action == "convert":
                creds = exchange_manifest_code(args.code, api_base=args.api_base)
                print(creds.model_dump_json(indent=2))
                return 0
            app_auth = default_github_app()
            if app_auth is None:
                print(
                    "Error: GitHub App is not configured. Set PMCURSOR_GITHUB_APP_ID and PMCURSOR_GITHUB_APP_PRIVATE_KEY.",
                    file=sys.stderr,
                )
                return 2
            if args.installation_id <= 0:
                print(
                    "Error: --installation-id is required for the token action.\n"
                    "  Try: python3 -m pmcursor.cli github-app token --installation-id 12345",
                    file=sys.stderr,
                )
                return 2
            token = app_auth.installation_token(args.installation_id)
            print(token.model_dump_json(indent=2))
            return 0
        except (GitHubAppError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

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

    if args.command == "summarize":
        prd_path = args.prd
        repo_path = args.repo
        if not _require_prd_and_repo(
            prd_path,
            repo_path,
            "python3 -m pmcursor.cli summarize --prd PROJECT_SPEC.md --repo .",
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
        llm_client = None if args.offline else default_llm_client()
        pm_summary = summarize_drift_report(report, llm_client=llm_client)
        if args.json:
            print(pm_summary.model_dump_json(indent=2))
        else:
            print(pm_summary.narrative_markdown, end="")
            print()
        return 0

    if args.command == "orgs":
        store_path = (
            args.store
            if args.store is not None
            else Path(os.environ.get(ENV_ORG_STORE, "") or DEFAULT_STORE_PATH)
        )
        try:
            registry = OrgRegistry(store_path)
            if args.action == "create":
                if not args.name.strip():
                    print(
                        "Error: --name is required for the create action.\n"
                        "  Try: python3 -m pmcursor.cli orgs create --name Acme",
                        file=sys.stderr,
                    )
                    return 2
                org, api_key = registry.create_org(
                    args.name, org_id=args.org_id or None
                )
                if args.json:
                    print(
                        json.dumps(
                            {
                                "org": org.model_dump(mode="json"),
                                "api_key": api_key,
                            },
                            indent=2,
                        )
                    )
                else:
                    print(f"Created org {org.org_id} ({org.name})")
                    print(f"API key (shown once): {api_key}")
                return 0
            if args.action == "list":
                orgs = registry.list_orgs()
                if args.json:
                    print(
                        json.dumps(
                            {
                                "orgs": [
                                    o.model_dump(mode="json") for o in orgs
                                ]
                            },
                            indent=2,
                        )
                    )
                else:
                    for o in orgs:
                        active = sum(1 for k in o.keys if not k.revoked)
                        print(f"{o.org_id}\t{o.name}\t{active} active key(s)")
                    if not orgs:
                        print("(no organizations)")
                return 0
            if args.action == "issue-key":
                if not args.org_id:
                    print(
                        "Error: --org-id is required for the issue-key action.",
                        file=sys.stderr,
                    )
                    return 2
                api_key = registry.issue_key(args.org_id, label=args.label)
                if args.json:
                    print(
                        json.dumps(
                            {"org_id": args.org_id, "api_key": api_key},
                            indent=2,
                        )
                    )
                else:
                    print(f"API key for {args.org_id} (shown once): {api_key}")
                return 0
            if args.action == "revoke-key":
                if not args.key_id:
                    print(
                        "Error: --key-id is required for the revoke-key action.",
                        file=sys.stderr,
                    )
                    return 2
                if not registry.revoke_key(args.key_id):
                    print(
                        f"Error: key id {args.key_id!r} not found.",
                        file=sys.stderr,
                    )
                    return 2
                print(f"Revoked key {args.key_id}")
                return 0
        except OrgRegistryError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
