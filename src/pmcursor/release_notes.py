from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pmcursor.drift import check_spec_drift
from pmcursor.models import (
    ADRContract,
    CompletionStatus,
    ModelContract,
    RepoMap,
    RouteContract,
    TelemetryContract,
)

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class ScopeCoverageReport(BaseModel):
    """Coverage of repository code contracts by a PRD specification."""

    model_config = ConfigDict(frozen=True)

    total_repo_contracts: int = Field(ge=0)
    covered_contracts: int = Field(ge=0)
    coverage_percent: float = Field(ge=0.0, le=100.0)
    uncovered_models: list[str] = Field(default_factory=list)
    uncovered_routes: list[str] = Field(default_factory=list)
    uncovered_telemetry: list[str] = Field(default_factory=list)
    uncovered_adrs: list[str] = Field(default_factory=list)


class ReleaseNotesEntry(BaseModel):
    """A single code contract touched by a diff."""

    model_config = ConfigDict(frozen=True)

    contract_kind: Literal["model", "route", "telemetry", "adr"]
    name: str
    citation: str
    covered_in_prd: bool
    summary: str


class ReleaseNotesReport(BaseModel):
    """Release notes and PRD scope coverage report for a diff."""

    model_config = ConfigDict(frozen=True)

    version: str
    prd_path: str
    drift_status: CompletionStatus
    alignment_score: int = Field(ge=0, le=100)
    changed_files_count: int = Field(ge=0)
    entries: list[ReleaseNotesEntry] = Field(default_factory=list)
    scope_coverage: ScopeCoverageReport
    markdown: str


def _is_model_covered(model: ModelContract, prd_markdown: str) -> bool:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(model.name)}(?![A-Za-z0-9_])"
    )
    return pattern.search(prd_markdown) is not None


def _is_route_covered(route: RouteContract, prd_lower: str) -> bool:
    return bool(
        (route.path and route.path.lower() in prd_lower)
        or (route.function_name and route.function_name.lower() in prd_lower)
    )


def _is_telemetry_covered(tel: TelemetryContract, prd_lower: str) -> bool:
    return bool(tel.event_name) and tel.event_name.lower() in prd_lower


def _is_adr_covered(adr: ADRContract, prd_lower: str) -> bool:
    return bool(
        (adr.adr_id and adr.adr_id.lower() in prd_lower)
        or (adr.title and adr.title.lower() in prd_lower)
    )


def compute_scope_coverage(
    prd_markdown: str, repo_map: RepoMap
) -> ScopeCoverageReport:
    """Compute how many indexed RepoMap contracts are referenced in prd_markdown."""
    prd_lower = prd_markdown.lower()

    uncovered_models: list[str] = []
    uncovered_routes: list[str] = []
    uncovered_telemetry: list[str] = []
    uncovered_adrs: list[str] = []

    covered = 0

    for model in repo_map.models:
        if _is_model_covered(model, prd_markdown):
            covered += 1
        else:
            uncovered_models.append(f"{model.name} ({model.citation})")

    for route in repo_map.routes:
        if _is_route_covered(route, prd_lower):
            covered += 1
        else:
            uncovered_routes.append(f"{route.method} {route.path} ({route.citation})")

    for tel in repo_map.telemetry:
        if _is_telemetry_covered(tel, prd_lower):
            covered += 1
        else:
            uncovered_telemetry.append(f"{tel.event_name} ({tel.citation})")

    for adr in repo_map.adrs:
        if _is_adr_covered(adr, prd_lower):
            covered += 1
        else:
            uncovered_adrs.append(f"{adr.adr_id} ({adr.citation})")

    total = (
        len(repo_map.models)
        + len(repo_map.routes)
        + len(repo_map.telemetry)
        + len(repo_map.adrs)
    )
    coverage_percent = round((covered / total) * 100.0, 1) if total > 0 else 100.0

    return ScopeCoverageReport(
        total_repo_contracts=total,
        covered_contracts=covered,
        coverage_percent=coverage_percent,
        uncovered_models=uncovered_models,
        uncovered_routes=uncovered_routes,
        uncovered_telemetry=uncovered_telemetry,
        uncovered_adrs=uncovered_adrs,
    )


def _normalize_diff_path(raw_path: str) -> str:
    cleaned = raw_path.strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _parse_diff_hunks(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Parse unified diff text into new-file (start, end) line ranges per file."""
    hunks: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None

    for raw_line in diff_text.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("+++ b/"):
            current_file = _normalize_diff_path(line[len("+++ b/") :])
            hunks.setdefault(current_file, [])
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
        hunks[current_file].append((start_line, end_line))

    return hunks


def _ranges_overlap(
    start_a: int, end_a: int, hunk_ranges: list[tuple[int, int]]
) -> bool:
    return any(start_a <= h_end and h_start <= end_a for h_start, h_end in hunk_ranges)


def _render_release_notes_markdown(
    *,
    version: str,
    prd_path: str,
    drift_status: CompletionStatus,
    alignment_score: int,
    changed_files_count: int,
    entries: list[ReleaseNotesEntry],
    scope_coverage: ScopeCoverageReport,
) -> str:
    lines: list[str] = [
        f"## Release Notes — {version}",
        "",
        f"- **PRD:** `{prd_path}`",
        f"- **Drift status:** `{drift_status}` (alignment score: **{alignment_score}/100**)",
        (
            f"- **Scope coverage:** {scope_coverage.covered_contracts}/"
            f"{scope_coverage.total_repo_contracts} ({scope_coverage.coverage_percent}%)"
        ),
        f"- **Changed files:** {changed_files_count}",
        "",
        "### Changed Contracts",
    ]

    if entries:
        for entry in entries:
            prd_badge = "documented" if entry.covered_in_prd else "undocumented"
            lines.append(
                f"- `{entry.name}` ({entry.contract_kind}, {prd_badge}) — "
                f"{entry.summary} [`{entry.citation}`]"
            )
    else:
        lines.append("- No indexed contracts changed in this diff.")

    lines.extend(["", "### Undocumented Code Contracts"])
    uncovered_all = [
        *scope_coverage.uncovered_models,
        *scope_coverage.uncovered_routes,
        *scope_coverage.uncovered_telemetry,
        *scope_coverage.uncovered_adrs,
    ]
    if uncovered_all:
        for item in uncovered_all:
            lines.append(f"- {item}")
    else:
        lines.append("- None. All indexed contracts are covered in the PRD.")

    return "\n".join(lines)


def generate_release_notes_and_coverage(
    prd_markdown: str,
    diff_text: str,
    repo_map: RepoMap,
    *,
    prd_path: str = "PRD.md",
    version: str = "Unreleased",
    repo_root: Path | None = None,
) -> ReleaseNotesReport:
    """Generate release notes from a unified diff and compute PRD scope coverage."""
    hunks_by_file = _parse_diff_hunks(diff_text)
    drift_report = check_spec_drift(
        prd_markdown,
        repo_map,
        prd_path=prd_path,
        repo_root=repo_root,
    )
    scope_coverage = compute_scope_coverage(prd_markdown, repo_map)
    prd_lower = prd_markdown.lower()

    entries: list[ReleaseNotesEntry] = []

    for model in repo_map.models:
        file_hunks = hunks_by_file.get(_normalize_diff_path(model.file_path))
        if not file_hunks:
            continue
        end_line = max([model.line, *(f.line for f in model.fields)])
        if _ranges_overlap(model.line, end_line, file_hunks):
            entries.append(
                ReleaseNotesEntry(
                    contract_kind="model",
                    name=model.name,
                    citation=model.citation,
                    covered_in_prd=_is_model_covered(model, prd_markdown),
                    summary=f"Model {model.name} ({len(model.fields)} fields)",
                )
            )

    for route in repo_map.routes:
        file_hunks = hunks_by_file.get(_normalize_diff_path(route.file_path))
        if not file_hunks:
            continue
        if _ranges_overlap(route.line, route.line, file_hunks):
            entries.append(
                ReleaseNotesEntry(
                    contract_kind="route",
                    name=f"{route.method} {route.path}",
                    citation=route.citation,
                    covered_in_prd=_is_route_covered(route, prd_lower),
                    summary=f"Route {route.method} {route.path} -> {route.function_name}",
                )
            )

    for tel in repo_map.telemetry:
        file_hunks = hunks_by_file.get(_normalize_diff_path(tel.file_path))
        if not file_hunks:
            continue
        if _ranges_overlap(tel.line, tel.line, file_hunks):
            entries.append(
                ReleaseNotesEntry(
                    contract_kind="telemetry",
                    name=tel.event_name,
                    citation=tel.citation,
                    covered_in_prd=_is_telemetry_covered(tel, prd_lower),
                    summary=f"Telemetry {tel.event_name} ({tel.source_kind})",
                )
            )

    for adr in repo_map.adrs:
        file_hunks = hunks_by_file.get(_normalize_diff_path(adr.file_path))
        if not file_hunks:
            continue
        if _ranges_overlap(adr.line, adr.line, file_hunks):
            entries.append(
                ReleaseNotesEntry(
                    contract_kind="adr",
                    name=adr.adr_id,
                    citation=adr.citation,
                    covered_in_prd=_is_adr_covered(adr, prd_lower),
                    summary=f"ADR {adr.adr_id}: {adr.title} [{adr.status}]",
                )
            )

    changed_files_count = len(hunks_by_file)
    alignment_score = drift_report.alignment_score.overall_score
    markdown = _render_release_notes_markdown(
        version=version,
        prd_path=prd_path,
        drift_status=drift_report.status,
        alignment_score=alignment_score,
        changed_files_count=changed_files_count,
        entries=entries,
        scope_coverage=scope_coverage,
    )

    return ReleaseNotesReport(
        version=version,
        prd_path=prd_path,
        drift_status=drift_report.status,
        alignment_score=alignment_score,
        changed_files_count=changed_files_count,
        entries=entries,
        scope_coverage=scope_coverage,
        markdown=markdown,
    )
