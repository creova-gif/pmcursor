from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from pmcursor.drift import check_spec_drift
from pmcursor.indexer import index_repository
from pmcursor.models import (
    CompletionStatus,
    DriftReport,
    PRImpactItem,
    PRImpactReport,
    RepoMap,
)
from pmcursor.tickets import TicketProvider

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class DriftAuditRequest(BaseModel):
    prd_markdown: str
    repo_root: str = "."
    prd_path: str = "PRD.md"


class SummarizeRequest(BaseModel):
    prd_markdown: str
    repo_root: str = "."
    prd_path: str = "PRD.md"
    offline: bool = False


class TicketAuditRequest(BaseModel):
    ticket_id: str
    title: str
    description: str
    provider: TicketProvider = "linear"
    repo_root: str = "."


class ChecklistRequest(BaseModel):
    repo_root: str = "."
    prd_markdown: str | None = None


class CanvasRequest(BaseModel):
    prd_markdown: str
    repo_root: str = "."
    prd_path: str = "PRD.md"


class ReleaseNotesRequest(BaseModel):
    prd_markdown: str
    diff_text: str = ""
    repo_root: str = "."
    prd_path: str = "PRD.md"
    version: str = "Unreleased"


class FlagAuditRequest(BaseModel):
    prd_markdown: str
    repo_root: str = "."


class TelemetryVerifyRequest(BaseModel):
    repo_root: str = "."
    events: list[dict[str, Any]]


class OrgDashboardSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo_root: str
    models_count: int
    routes_count: int
    telemetry_count: int
    adrs_count: int
    feature_flags_count: int
    alignment_score: int
    scope_coverage_percent: float
    p0_checklist_items: int
    status: CompletionStatus


class GitHubWebhookPayload(BaseModel):
    org_id: str = "default"
    prd_markdown: str
    diff_text: str
    prd_path: str = "PRD.md"
    repo_root: str = "."


class PublishCommentRequest(BaseModel):
    provider: Literal["github", "linear", "jira"]
    target: str
    body: str
    jira_base_url: str | None = None
    dry_run: bool = True


def audit_prd_against_repo(request: DriftAuditRequest) -> DriftReport:
    """Programmatic API entrypoint for auditing PRD drift against a local repository."""
    root = Path(request.repo_root).resolve()
    repo_map: RepoMap = index_repository(root)
    return check_spec_drift(
        request.prd_markdown,
        repo_map,
        prd_path=request.prd_path,
        repo_root=root,
    )


def _hmac_sha256_hex(payload_body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()


def verify_github_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify a GitHub webhook X-Hub-Signature-256 HMAC-SHA256 signature."""
    if not secret or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + _hmac_sha256_hex(payload_body, secret)
    return hmac.compare_digest(expected, signature_header)


def verify_linear_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify a Linear webhook Linear-Signature raw hex HMAC-SHA256 signature."""
    if not secret or not signature_header:
        return False
    expected = _hmac_sha256_hex(payload_body, secret)
    return hmac.compare_digest(expected, signature_header.strip())


def verify_jira_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify a Jira webhook X-Hub-Signature sha256=<hex> HMAC-SHA256 signature."""
    return verify_github_signature(payload_body, signature_header, secret)


def parse_linear_webhook_issue(data: dict[str, Any]) -> tuple[str, str, str] | None:
    """Extract (ticket_id, title, description) from a Linear Issue webhook payload."""
    if data.get("type") != "Issue":
        return None
    issue = data.get("data")
    if not isinstance(issue, dict):
        return None
    ticket_id = issue.get("identifier") or issue.get("id")
    if not ticket_id or not str(ticket_id).strip():
        return None
    title = issue.get("title") or ""
    description = issue.get("description") or ""
    return (str(ticket_id), str(title), str(description))


def parse_jira_webhook_issue(data: dict[str, Any]) -> tuple[str, str, str] | None:
    """Extract (ticket_id, title, description) from a Jira issue webhook payload."""
    issue = data.get("issue")
    if not isinstance(issue, dict):
        return None
    ticket_id = issue.get("key") or issue.get("id")
    if not ticket_id or not str(ticket_id).strip():
        return None
    raw_fields = issue.get("fields")
    fields: dict[str, Any] = raw_fields if isinstance(raw_fields, dict) else {}
    title = fields.get("summary") or ""
    raw_description = fields.get("description")
    description = raw_description if isinstance(raw_description, str) else ""
    return (str(ticket_id), str(title), description)


def parse_unified_diff_ranges(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Parse unified diff text into new-file line ranges keyed by relative path."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/") :].strip()
            continue
        if line.startswith(("+++ ", "diff --git ")):
            current_file = None
            continue
        if current_file is None:
            continue
        match = _HUNK_HEADER_RE.match(line)
        if match is None:
            continue
        start_line = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        end_line = max(start_line, start_line + count - 1)
        ranges.setdefault(current_file, []).append((start_line, end_line))

    return ranges


def _ranges_overlap(
    start_a: int,
    end_a: int,
    hunk_ranges: list[tuple[int, int]],
) -> bool:
    return any(start_a <= h_end and h_start <= end_a for h_start, h_end in hunk_ranges)


def _format_pr_comment(
    org_id: str,
    prd_path: str,
    touched_contracts: list[PRImpactItem],
    impacted_refs: list[str],
    drift_report: DriftReport,
) -> str:
    score = drift_report.alignment_score.overall_score
    lines = [
        f"### PMCursor PR Impact (`{org_id}`)",
        f"- **PRD:** `{prd_path}`",
        f"- **Drift Status:** `{drift_report.status}` (Alignment Score: **{score}/100**)",
        f"- **Touched Contracts:** {len(touched_contracts)}",
        f"- **PRD References Impacted:** {len(impacted_refs)}",
    ]
    if touched_contracts:
        lines.append("")
        lines.append("#### Touched Contracts")
        for item in touched_contracts:
            ref_tag = "referenced in PRD" if item.referenced_in_prd else "not referenced in PRD"
            lines.append(
                f"- `{item.contract_kind}` **{item.name}** (`{item.citation}`) — {ref_tag}"
            )
    if impacted_refs:
        lines.append("")
        lines.append("#### Impacted PRD References")
        for ref in impacted_refs:
            lines.append(f"- `{ref}`")
    return "\n".join(lines)


def compute_pr_impact(
    prd_md: str,
    diff_text: str,
    repo_map: RepoMap,
    *,
    prd_path: str = "PRD.md",
    org_id: str = "default",
) -> PRImpactReport:
    """Compute contract impact and PRD drift for a unified diff against a RepoMap."""
    diff_ranges = parse_unified_diff_ranges(diff_text)
    touched_contracts: list[PRImpactItem] = []

    for model in repo_map.models:
        file_ranges = diff_ranges.get(model.file_path)
        if not file_ranges:
            continue
        end_line = max((f.line for f in model.fields), default=model.line)
        if _ranges_overlap(model.line, end_line, file_ranges):
            referenced = model.name in prd_md or model.citation in prd_md
            touched_contracts.append(
                PRImpactItem(
                    contract_kind="model",
                    name=model.name,
                    citation=model.citation,
                    referenced_in_prd=referenced,
                )
            )

    for route in repo_map.routes:
        file_ranges = diff_ranges.get(route.file_path)
        if not file_ranges:
            continue
        if _ranges_overlap(route.line, route.line, file_ranges):
            referenced = (
                route.path in prd_md
                or route.function_name in prd_md
                or route.citation in prd_md
            )
            touched_contracts.append(
                PRImpactItem(
                    contract_kind="route",
                    name=f"{route.method} {route.path}",
                    citation=route.citation,
                    referenced_in_prd=referenced,
                )
            )

    for telemetry in repo_map.telemetry:
        file_ranges = diff_ranges.get(telemetry.file_path)
        if not file_ranges:
            continue
        if _ranges_overlap(telemetry.line, telemetry.line, file_ranges):
            referenced = telemetry.event_name in prd_md or telemetry.citation in prd_md
            touched_contracts.append(
                PRImpactItem(
                    contract_kind="telemetry",
                    name=telemetry.event_name,
                    citation=telemetry.citation,
                    referenced_in_prd=referenced,
                )
            )

    for adr in repo_map.adrs:
        file_ranges = diff_ranges.get(adr.file_path)
        if not file_ranges:
            continue
        if _ranges_overlap(adr.line, adr.line, file_ranges):
            referenced = (
                adr.adr_id in prd_md
                or adr.title in prd_md
                or adr.citation in prd_md
            )
            touched_contracts.append(
                PRImpactItem(
                    contract_kind="adr",
                    name=adr.adr_id,
                    citation=adr.citation,
                    referenced_in_prd=referenced,
                )
            )

    impacted_refs = [item.name for item in touched_contracts if item.referenced_in_prd]
    drift_report = check_spec_drift(
        prd_md,
        repo_map,
        prd_path=prd_path,
        repo_root=Path(repo_map.repo_root),
    )
    markdown_comment = _format_pr_comment(
        org_id=org_id,
        prd_path=prd_path,
        touched_contracts=touched_contracts,
        impacted_refs=impacted_refs,
        drift_report=drift_report,
    )

    return PRImpactReport(
        prd_path=prd_path,
        org_id=org_id,
        touched_contracts=touched_contracts,
        impacted_prd_references=impacted_refs,
        drift_report=drift_report,
        markdown_comment=markdown_comment,
    )


def handle_github_webhook(
    payload_body: bytes,
    signature_header: str,
    secret: str,
    *,
    allowed_workspace_root: Path | None = None,
) -> PRImpactReport:
    """Verify GitHub webhook signature, validate payload, and compute PR impact."""
    if not verify_github_signature(payload_body, signature_header, secret):
        raise PermissionError("Invalid GitHub webhook signature")
    payload = GitHubWebhookPayload.model_validate_json(payload_body)
    root = Path(payload.repo_root).resolve()
    if allowed_workspace_root is not None and not root.is_relative_to(
        allowed_workspace_root.resolve()
    ):
        raise PermissionError("Repository root outside allowed workspace")
    repo_map = index_repository(root)
    return compute_pr_impact(
        payload.prd_markdown,
        payload.diff_text,
        repo_map,
        prd_path=payload.prd_path,
        org_id=payload.org_id,
    )
