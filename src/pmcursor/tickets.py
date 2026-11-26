from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pmcursor.drift import check_spec_drift
from pmcursor.models import DriftReport, RepoMap

TicketProvider = Literal["linear", "jira"]


class TicketSyncReport(BaseModel):
    """Audit report synchronizing a Linear or Jira ticket against a RepoMap."""

    model_config = ConfigDict(frozen=True)

    ticket_id: str
    provider: TicketProvider
    title: str
    drift_report: DriftReport
    comment_markdown: str


def _escape_markdown_cell(value: str) -> str:
    """Normalize line breaks and escape pipe characters for a Markdown table cell."""
    normalized = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return normalized.strip().replace("|", "\\|")


def _format_ticket_comment(
    *,
    ticket_id: str,
    provider: TicketProvider,
    title: str,
    report: DriftReport,
) -> str:
    """Format a DriftReport as a concise Markdown comment for a ticket."""
    score = report.alignment_score
    normalized_title = title.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    lines = [
        f"## PMCursor Ticket Audit — `{provider}:{ticket_id}`",
        f"**Title:** {normalized_title}",
        "",
        f"- **Status:** `{report.status}`",
        f"- **Alignment score:** **{score.overall_score}/100**",
        (
            f"- **Matched contracts:** "
            f"{report.matched_contracts}/{report.total_spec_contracts}"
        ),
        (
            f"- **Fabricated citations:** "
            f"{report.fabricated_citations_count}/{report.total_citations_checked}"
        ),
        "",
    ]
    if not report.findings:
        lines.append("No spec-vs-code drift detected.")
    else:
        lines.extend(
            [
                "| Severity | Category | Spec reference | Code citation | Message |",
                "|:---------|:---------|:---------------|:--------------|:--------|",
            ]
        )
        for finding in report.findings:
            severity = _escape_markdown_cell(finding.severity.upper())
            category = _escape_markdown_cell(finding.category)
            spec_ref = _escape_markdown_cell(finding.spec_reference)
            cite = (
                f"`{_escape_markdown_cell(finding.code_citation)}`"
                if finding.code_citation
                else "None"
            )
            message = _escape_markdown_cell(finding.message)
            lines.append(
                f"| `{severity}` | `{category}` "
                f"| `{spec_ref}` | {cite} | {message} |"
            )
    return "\n".join(lines) + "\n"


def audit_ticket_against_repo(
    ticket_id: str,
    title: str,
    description: str,
    repo_map: RepoMap,
    *,
    provider: TicketProvider = "linear",
    repo_root: Path | None = None,
) -> TicketSyncReport:
    """Audit a Linear or Jira ticket description against an AST-indexed RepoMap."""
    drift_report = check_spec_drift(
        description,
        repo_map,
        prd_path=f"{provider}:{ticket_id}",
        repo_root=repo_root,
    )
    comment_markdown = _format_ticket_comment(
        ticket_id=ticket_id,
        provider=provider,
        title=title,
        report=drift_report,
    )
    return TicketSyncReport(
        ticket_id=ticket_id,
        provider=provider,
        title=title,
        drift_report=drift_report,
        comment_markdown=comment_markdown,
    )
