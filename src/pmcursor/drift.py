from __future__ import annotations

import re
from pathlib import Path

from pmcursor.models import (
    CompletionStatus,
    DriftFinding,
    DriftReport,
    FieldContract,
    FixPrdResult,
    ModelContract,
    RepoMap,
    RouteContract,
    SpecAlignmentScore,
    TelemetryContract,
)

CITATION_RE = re.compile(
    r"(?<![A-Za-z0-9_://])([A-Za-z0-9_./-]+\.(?:py|ts|tsx|js|sql|md|json|yaml|yml|mdc)):(\d+)(?:-\d+)?"
)

SPEC_FIELD_RE = re.compile(
    r"`([A-Z][A-Za-z0-9_]*)\.([a-z_][a-z0-9_]*)\s*:\s*([^`]+)`"
)

SPEC_ROUTE_RE = re.compile(
    r"`(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_/{}-]*)`"
)

SPEC_TELEMETRY_RE = re.compile(
    r"`telemetry:\s*([A-Za-z0-9_.-]+)(?:\(([^)]*)\))?`"
)

SPEC_ADR_RE = re.compile(r"\b(ADR-\d{3})\b", re.IGNORECASE)

TYPE_ALIASES: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "boolean": "bool",
    "number": "float",
    "float": "float",
    "uuid": "UUID",
    "datetime": "datetime",
    "list": "list",
    "dict": "dict",
}


def _normalize_type(raw_type: str) -> str:
    cleaned = raw_type.strip().replace(" ", "")
    OptionalMatch = re.match(r"^Optional\[(.+)\]$", cleaned)
    if OptionalMatch:
        inner = _normalize_type(OptionalMatch.group(1))
        return f"{inner}|None"
    if "|" in cleaned:
        parts = [_normalize_type(p) for p in cleaned.split("|")]
        return "|".join(parts)
    lower = cleaned.lower()
    if lower in TYPE_ALIASES:
        return TYPE_ALIASES[lower]
    return cleaned


def _normalize_route_path(path: str) -> str:
    normalized = re.sub(r"\{[^}]+\}", "{param}", path.strip().rstrip("/"))
    return normalized or "/"


def _verify_citations(
    prd_md: str, repo_map: RepoMap, repo_root: Path | None
) -> tuple[int, list[DriftFinding]]:
    findings: list[DriftFinding] = []
    seen: set[tuple[str, int]] = set()
    root = repo_root or Path(repo_map.repo_root)
    resolved_root = root.resolve()
    known_files = set(repo_map.indexed_files)

    for match in CITATION_RE.finditer(prd_md):
        rel_path = match.group(1)
        while rel_path.startswith("./"):
            rel_path = rel_path[2:]
        line_no = int(match.group(2))
        if rel_path.startswith("path/to/"):
            continue
        key = (rel_path, line_no)
        if key in seen:
            continue
        seen.add(key)

        candidate = (root / rel_path).resolve()
        if not candidate.is_relative_to(resolved_root):
            findings.append(
                DriftFinding(
                    category="fabricated_citation",
                    severity="critical",
                    spec_reference=f"{rel_path}:{line_no}",
                    code_citation=None,
                    message=f"Cited path '{rel_path}' escapes repository root.",
                    remediation=f"Replace '{rel_path}:{line_no}' with a valid path inside the repository root.",
                )
            )
            continue

        exists_in_repo = rel_path in known_files or candidate.is_file()
        if not exists_in_repo:
            findings.append(
                DriftFinding(
                    category="fabricated_citation",
                    severity="critical",
                    spec_reference=f"{rel_path}:{line_no}",
                    code_citation=None,
                    message=f"Cited file '{rel_path}' does not exist in repository.",
                    remediation=f"Remove fabricated path '{rel_path}:{line_no}' or run `pmcursor index --repo .` to locate the real contract file.",
                )
            )
            continue

        if candidate.is_file():
            try:
                total_lines = len(candidate.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeDecodeError):
                total_lines = 0
            if total_lines > 0 and line_no > total_lines:
                findings.append(
                    DriftFinding(
                        category="fabricated_citation",
                        severity="high",
                        spec_reference=f"{rel_path}:{line_no}",
                        code_citation=f"{rel_path}:1",
                        message=(
                            f"Cited line {line_no} in '{rel_path}' exceeds file length ({total_lines} lines)."
                        ),
                        remediation=f"Update citation to a valid line within '{rel_path}' (1..{total_lines}).",
                    )
                )

    return len(seen), findings


def _check_model_contracts(
    prd_md: str, models_by_name: dict[str, ModelContract]
) -> tuple[int, int, list[DriftFinding]]:
    findings: list[DriftFinding] = []
    total_specs = 0
    matched_specs = 0
    seen_specs: set[tuple[str, str]] = set()
    reported_missing_models: set[str] = set()

    for match in SPEC_FIELD_RE.finditer(prd_md):
        model_name, field_name, expected_type = (
            match.group(1),
            match.group(2),
            match.group(3).strip(),
        )
        if model_name in {"ModelName", "Model"}:
            continue
        spec_key = (model_name, field_name)
        if spec_key in seen_specs:
            continue
        seen_specs.add(spec_key)
        total_specs += 1
        spec_ref = f"{model_name}.{field_name}: {expected_type}"

        model_contract = models_by_name.get(model_name)
        if model_contract is None:
            if model_name not in reported_missing_models:
                reported_missing_models.add(model_name)
                findings.append(
                    DriftFinding(
                        category="missing_model",
                        severity="high",
                        spec_reference=spec_ref,
                        code_citation=None,
                        message=f"Model '{model_name}' specified in PRD was not found in indexed AST contracts.",
                        remediation=f"Define Pydantic/dataclass model '{model_name}' or update the PRD model name.",
                    )
                )
            continue

        field_map = {f.name: f for f in model_contract.fields}
        field_contract = field_map.get(field_name)
        if field_contract is None:
            findings.append(
                DriftFinding(
                    category="missing_field",
                    severity="high",
                    spec_reference=spec_ref,
                    code_citation=model_contract.citation,
                    message=(
                        f"Field '{field_name}' on model '{model_name}' is missing in {model_contract.citation}."
                    ),
                    remediation=(
                        f"Add `{field_name}: {expected_type}` to `{model_name}` at {model_contract.citation} or update the PRD."
                    ),
                )
            )
            continue

        norm_expected = _normalize_type(expected_type)
        norm_actual = _normalize_type(field_contract.type_annotation)
        if norm_expected != norm_actual:
            field_citation = f"{model_contract.file_path}:{field_contract.line}"
            findings.append(
                DriftFinding(
                    category="type_mismatch",
                    severity="medium",
                    spec_reference=spec_ref,
                    code_citation=field_citation,
                    message=(
                        f"Type mismatch on '{model_name}.{field_name}': PRD expects '{expected_type}' "
                        f"but code has '{field_contract.type_annotation}' at {field_citation}."
                    ),
                    remediation=(
                        f"Align '{model_name}.{field_name}' type at {field_citation} with PRD ('{expected_type}')."
                    ),
                )
            )
            continue

        matched_specs += 1

    return total_specs, matched_specs, findings


def _check_route_contracts(
    prd_md: str, routes: list[RouteContract]
) -> tuple[int, int, list[DriftFinding]]:
    findings: list[DriftFinding] = []
    total_routes = 0
    matched_routes = 0
    seen_routes: set[tuple[str, str]] = set()

    routes_by_norm_path: dict[str, list[RouteContract]] = {}
    for route in routes:
        norm_path = _normalize_route_path(route.path)
        routes_by_norm_path.setdefault(norm_path, []).append(route)

    for match in SPEC_ROUTE_RE.finditer(prd_md):
        method, raw_path = match.group(1).upper(), match.group(2).strip()
        route_key = (method, raw_path)
        if route_key in seen_routes:
            continue
        seen_routes.add(route_key)
        total_routes += 1
        spec_ref = f"{method} {raw_path}"
        norm_path = _normalize_route_path(raw_path)

        candidates = routes_by_norm_path.get(norm_path, [])
        if not candidates:
            findings.append(
                DriftFinding(
                    category="missing_route",
                    severity="high",
                    spec_reference=spec_ref,
                    code_citation=None,
                    message=f"Endpoint '{spec_ref}' specified in PRD is not registered in any indexed router.",
                    remediation=f"Implement `{spec_ref}` in your FastAPI router or remove it from the PRD.",
                )
            )
            continue

        exact_method = [c for c in candidates if c.method.upper() == method]
        if not exact_method:
            actual = candidates[0]
            findings.append(
                DriftFinding(
                    category="method_mismatch",
                    severity="medium",
                    spec_reference=spec_ref,
                    code_citation=actual.citation,
                    message=(
                        f"Endpoint '{raw_path}' uses HTTP {actual.method} at {actual.citation}, "
                        f"but PRD specifies HTTP {method}."
                    ),
                    remediation=f"Change decorator at {actual.citation} to `@{actual.method.lower()}` -> `@{method.lower()}` or update the PRD.",
                )
            )
            continue

        matched_routes += 1

    return total_routes, matched_routes, findings


def _check_telemetry_contracts(
    prd_md: str, telemetry: list[TelemetryContract]
) -> tuple[int, int, list[DriftFinding]]:
    findings: list[DriftFinding] = []
    total_events = 0
    matched_events = 0
    seen_events: set[str] = set()

    telemetry_by_name: dict[str, list[TelemetryContract]] = {}
    for contract in telemetry:
        telemetry_by_name.setdefault(contract.event_name, []).append(contract)

    for match in SPEC_TELEMETRY_RE.finditer(prd_md):
        event_name = match.group(1).strip()
        if event_name in seen_events:
            continue
        seen_events.add(event_name)
        total_events += 1

        raw_props = match.group(2)
        expected_props = (
            [p.strip() for p in raw_props.split(",") if p.strip()]
            if raw_props is not None
            else []
        )
        spec_ref = (
            f"telemetry:{event_name}({', '.join(expected_props)})"
            if expected_props
            else f"telemetry:{event_name}"
        )

        candidates = telemetry_by_name.get(event_name, [])
        if not candidates:
            findings.append(
                DriftFinding(
                    category="missing_telemetry",
                    severity="high",
                    spec_reference=spec_ref,
                    code_citation=None,
                    message=(
                        f"Telemetry event '{event_name}' specified in PRD was not found in indexed telemetry contracts."
                    ),
                    remediation=f"Emit telemetry event '{event_name}' in code or remove it from the PRD.",
                )
            )
            continue

        if expected_props:
            expected_set = set(expected_props)
            matching_contract = next(
                (c for c in candidates if expected_set.issubset(c.properties)),
                None,
            )
            if matching_contract is None:
                actual = candidates[0]
                actual_props = set(actual.properties)
                missing_props = [p for p in expected_props if p not in actual_props]
                findings.append(
                    DriftFinding(
                        category="telemetry_property_mismatch",
                        severity="medium",
                        spec_reference=spec_ref,
                        code_citation=actual.citation,
                        message=(
                            f"Telemetry event '{event_name}' at {actual.citation} is missing properties: "
                            f"{', '.join(missing_props)}."
                        ),
                        remediation=(
                            f"Add {', '.join(missing_props)} to '{event_name}' at {actual.citation} or update the PRD."
                        ),
                    )
                )
                continue

        matched_events += 1

    return total_events, matched_events, findings


def _check_adr_contracts(prd_md: str, repo_map: RepoMap) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    indexed_adrs = {adr.adr_id.upper(): adr for adr in repo_map.adrs}
    seen_adrs: set[str] = set()

    for match in SPEC_ADR_RE.finditer(prd_md):
        adr_id = match.group(1).upper()
        if adr_id in {"ADR-000"} or adr_id in seen_adrs:
            continue
        seen_adrs.add(adr_id)
        if adr_id not in indexed_adrs:
            findings.append(
                DriftFinding(
                    category="unindexed_adr",
                    severity="medium",
                    spec_reference=adr_id,
                    code_citation=None,
                    message=f"PRD references '{adr_id}', which does not exist in `docs/adr/`.",
                    remediation=f"Create `docs/adr/{adr_id.lower()}-*.md` using `docs/adr/000-template.md`.",
                )
            )
    return findings


def _compute_alignment_score(
    prd_md: str,
    total_contracts: int,
    matched_contracts: int,
    total_citations: int,
    fabricated_citations: int,
    unindexed_adrs_count: int,
) -> SpecAlignmentScore:
    contract_ratio = (
        matched_contracts / total_contracts if total_contracts > 0 else 1.0
    )
    citation_ratio = (
        max(0, total_citations - fabricated_citations) / total_citations
        if total_citations > 0
        else 1.0
    )
    adr_penalty = min(0.25, unindexed_adrs_count * 0.15)
    deterministic_raw = ((contract_ratio * 0.65) + (citation_ratio * 0.35)) - adr_penalty
    deterministic_score = max(0, min(100, round(deterministic_raw * 100)))

    lower_md = prd_md.lower()
    has_acceptance_cards = (
        "protects=" in lower_md and "fails_when=" in lower_md and "no_claim=" in lower_md
    )
    has_rollback = "rollback" in lower_md
    has_out_of_scope = "out of scope" in lower_md or "non-goals" in lower_md
    has_adr_refs = bool(SPEC_ADR_RE.search(prd_md))

    workflow_points = (
        (35 if has_acceptance_cards else 0)
        + (25 if has_rollback else 0)
        + (20 if has_out_of_scope else 0)
        + (20 if has_adr_refs else 0)
    )
    workflow_score = max(0, min(100, workflow_points))
    overall_score = round((deterministic_score * 0.7) + (workflow_score * 0.3))

    return SpecAlignmentScore(
        overall_score=overall_score,
        deterministic_score=deterministic_score,
        workflow_score=workflow_score,
        has_acceptance_cards=has_acceptance_cards,
        has_rollback_section=has_rollback,
        has_out_of_scope_section=has_out_of_scope,
        has_adr_references=has_adr_refs,
    )


def check_spec_drift(
    prd_md: str,
    repo_map: RepoMap,
    *,
    prd_path: str = "PRD.md",
    repo_root: Path | None = None,
) -> DriftReport:
    """Compare a PRD markdown specification against an AST-indexed RepoMap."""
    total_citations, citation_findings = _verify_citations(prd_md, repo_map, repo_root)
    models_by_name = {m.name: m for m in repo_map.models}
    model_total, model_matched, model_findings = _check_model_contracts(
        prd_md, models_by_name
    )
    route_total, route_matched, route_findings = _check_route_contracts(
        prd_md, repo_map.routes
    )
    telemetry_total, telemetry_matched, telemetry_findings = _check_telemetry_contracts(
        prd_md, repo_map.telemetry
    )
    adr_findings = _check_adr_contracts(prd_md, repo_map)

    all_findings = [
        *citation_findings,
        *model_findings,
        *route_findings,
        *telemetry_findings,
        *adr_findings,
    ]
    total_contracts = model_total + route_total + telemetry_total
    matched_contracts = model_matched + route_matched + telemetry_matched
    fabricated_count = len(citation_findings)

    alignment_score = _compute_alignment_score(
        prd_md=prd_md,
        total_contracts=total_contracts,
        matched_contracts=matched_contracts,
        total_citations=total_citations,
        fabricated_citations=fabricated_count,
        unindexed_adrs_count=len(adr_findings),
    )

    status: CompletionStatus
    if fabricated_count > 0:
        status = "BLOCKED"
    elif all_findings:
        status = "DONE_WITH_CONCERNS"
    else:
        status = "DONE"

    return DriftReport(
        prd_path=prd_path,
        status=status,
        alignment_score=alignment_score,
        total_spec_contracts=total_contracts,
        matched_contracts=matched_contracts,
        total_citations_checked=total_citations,
        fabricated_citations_count=fabricated_count,
        findings=all_findings,
    )


def format_drift_report_markdown(report: DriftReport) -> str:
    """Format a DriftReport as a structured Markdown document."""
    score = report.alignment_score
    lines = [
        f"# PMCursor spec drift report for `{report.prd_path}`",
        "",
        "## 1. Overview",
        f"- **Completion status:** `{report.status}`",
        (
            f"- **Spec alignment score:** **{score.overall_score}/100** "
            f"(Deterministic: {score.deterministic_score}/100, Workflow: {score.workflow_score}/100)"
        ),
        f"- **Contract coverage:** {report.matched_contracts}/{report.total_spec_contracts} matched",
        (
            f"- **Citation verification:** {report.total_citations_checked} checked, "
            f"**{report.fabricated_citations_count} fabricated**"
        ),
        "",
        "## 2. Workflow readiness checklist",
        f"- [{'x' if score.has_acceptance_cards else ' '}] Acceptance cards (`protects`, `fails_when`, `no_claim`)",
        f"- [{'x' if score.has_adr_references else ' '}] ADR references (`ADR-NNN`)",
        f"- [{'x' if score.has_out_of_scope_section else ' '}] Explicit out of scope section",
        f"- [{'x' if score.has_rollback_section else ' '}] Rollback strategy",
        "",
        "## 3. Drift findings",
    ]
    if not report.findings:
        lines.append("No spec-vs-code drift or fabricated citations detected.")
    else:
        lines.extend(
            [
                "",
                "| Severity | Category | Spec reference | Code citation | Message |",
                "|:---------|:---------|:---------------|:--------------|:--------|",
            ]
        )
        for f in report.findings:
            cite = f"`{f.code_citation}`" if f.code_citation else "None"
            lines.append(
                f"| `{f.severity.upper()}` | `{f.category}` | `{f.spec_reference}` | {cite} | {f.message} |"
            )
    return "\n".join(lines) + "\n"


def fix_prd_markdown(
    prd_md: str,
    repo_map: RepoMap,
    *,
    prd_path: str = "PRD.md",
    repo_root: Path | None = None,
) -> FixPrdResult:
    """Repair stale citation line numbers and field type annotations in PRD markdown."""
    root = repo_root or Path(repo_map.repo_root)
    resolved_root = root.resolve()

    contract_locations: list[tuple[str, int]] = [
        *((m.file_path, m.line) for m in repo_map.models),
        *((r.file_path, r.line) for r in repo_map.routes),
        *((t.file_path, t.line) for t in repo_map.telemetry),
        *((a.file_path, a.line) for a in repo_map.adrs),
    ]
    contract_line_by_file: dict[str, int] = {}
    for file_path, line in contract_locations:
        norm_file = file_path.removeprefix("./")
        if (
            norm_file not in contract_line_by_file
            or line < contract_line_by_file[norm_file]
        ):
            contract_line_by_file[norm_file] = line

    fixed_citations_count = 0

    def _replace_citation(match: re.Match[str]) -> str:
        nonlocal fixed_citations_count
        raw_path = match.group(1)
        rel_path = raw_path
        while rel_path.startswith("./"):
            rel_path = rel_path[2:]
        if rel_path.startswith("path/to/"):
            return match.group(0)
        line_no = int(match.group(2))
        candidate = (root / rel_path).resolve()
        if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
            return match.group(0)
        try:
            total_lines = len(candidate.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            return match.group(0)
        if total_lines == 0 or line_no <= total_lines:
            return match.group(0)
        contract_line = contract_line_by_file.get(rel_path)
        if contract_line is None:
            return match.group(0)
        target_line = min(contract_line, total_lines)
        if target_line == line_no:
            return match.group(0)
        fixed_citations_count += 1
        return f"{raw_path}:{target_line}"

    updated = CITATION_RE.sub(_replace_citation, prd_md)

    fields_by_model: dict[str, dict[str, FieldContract]] = {
        m.name: {f.name: f for f in m.fields} for m in repo_map.models
    }
    fixed_types_count = 0

    def _replace_field(match: re.Match[str]) -> str:
        nonlocal fixed_types_count
        model_name = match.group(1)
        field_name = match.group(2)
        expected_type = match.group(3).strip()
        if model_name in {"ModelName", "Model"}:
            return match.group(0)
        field_map = fields_by_model.get(model_name)
        if field_map is None:
            return match.group(0)
        actual = field_map.get(field_name)
        if actual is None:
            return match.group(0)
        if _normalize_type(expected_type) != _normalize_type(actual.type_annotation):
            fixed_types_count += 1
            return f"`{model_name}.{field_name}: {actual.type_annotation}`"
        return match.group(0)

    updated = SPEC_FIELD_RE.sub(_replace_field, updated)

    return FixPrdResult(
        prd_path=prd_path,
        updated_markdown=updated,
        fixed_citations_count=fixed_citations_count,
        fixed_types_count=fixed_types_count,
        applied=False,
    )
