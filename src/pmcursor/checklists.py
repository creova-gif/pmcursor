from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pmcursor.drift import check_spec_drift
from pmcursor.models import (
    FieldContract,
    ModelContract,
    RepoMap,
    RouteContract,
    TelemetryContract,
)

EdgeCaseCategory = Literal["schema_validation", "api_auth_error", "telemetry", "spec_drift"]
EdgeCasePriority = Literal["P0", "P1", "P2"]

_WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MAX_FIELDS_PER_MODEL = 3


class EdgeCaseItem(BaseModel):
    """Single codebase-cited QA or edge-case verification item."""

    model_config = ConfigDict(frozen=True)

    priority: EdgeCasePriority
    category: EdgeCaseCategory
    contract_name: str
    citation: str
    scenario: str
    expected_behavior: str


class EdgeCaseChecklist(BaseModel):
    """Complete edge-case and QA checklist generated from a RepoMap and optional PRD."""

    model_config = ConfigDict(frozen=True)

    repo_root: str
    total_items: int
    p0_count: int
    items: list[EdgeCaseItem]
    markdown: str


def _is_optional_field(field: FieldContract) -> bool:
    """Return True when a field is optional or nullable in its type contract."""
    if not field.required:
        return True
    normalized = field.type_annotation.replace(" ", "")
    return (
        "Optional[" in normalized
        or "|None" in normalized
        or "None|" in normalized
    )


def _select_representative_fields(
    fields: list[FieldContract],
    limit: int = _MAX_FIELDS_PER_MODEL,
) -> list[FieldContract]:
    """Select up to `limit` representative fields, covering both optional and required."""
    if len(fields) <= limit:
        return list(fields)

    selected: list[FieldContract] = []
    seen_names: set[str] = set()

    first_required = next((f for f in fields if not _is_optional_field(f)), None)
    first_optional = next((f for f in fields if _is_optional_field(f)), None)

    for candidate in (first_required, first_optional):
        if candidate is not None and candidate.name not in seen_names and len(selected) < limit:
            selected.append(candidate)
            seen_names.add(candidate.name)

    for field in fields:
        if len(selected) >= limit:
            break
        if field.name not in seen_names:
            selected.append(field)
            seen_names.add(field.name)

    return selected


def _build_model_items(model: ModelContract) -> list[EdgeCaseItem]:
    """Generate schema validation edge cases for a ModelContract."""
    items: list[EdgeCaseItem] = []
    for field in _select_representative_fields(model.fields):
        citation = f"{model.file_path}:{field.line}"
        contract_name = f"{model.name}.{field.name}"
        if _is_optional_field(field):
            items.append(
                EdgeCaseItem(
                    priority="P1",
                    category="schema_validation",
                    contract_name=contract_name,
                    citation=citation,
                    scenario=(
                        f"Omit or pass null for optional field `{field.name}` "
                        f"(`{field.type_annotation}`)"
                    ),
                    expected_behavior=(
                        "Handles null or omitted value safely without raising an unhandled error"
                    ),
                )
            )
        else:
            items.append(
                EdgeCaseItem(
                    priority="P1",
                    category="schema_validation",
                    contract_name=contract_name,
                    citation=citation,
                    scenario=(
                        f"Omit or pass invalid type for required field `{field.name}` "
                        f"(`{field.type_annotation}`)"
                    ),
                    expected_behavior=(
                        "Rejects input with a deterministic validation error"
                    ),
                )
            )
    return items


def _build_route_items(route: RouteContract) -> list[EdgeCaseItem]:
    """Generate API auth and error edge cases for a RouteContract."""
    items: list[EdgeCaseItem] = []
    method = route.method.upper()
    contract_name = f"{method} {route.path}"

    if method in _WRITE_METHODS:
        items.append(
            EdgeCaseItem(
                priority="P1",
                category="api_auth_error",
                contract_name=contract_name,
                citation=route.citation,
                scenario=(
                    f"Call `{contract_name}` without valid credentials "
                    "or with unauthorized scope"
                ),
                expected_behavior=(
                    "Returns 401 Unauthorized or 403 Forbidden without mutating state"
                ),
            )
        )
        if route.request_model is not None:
            items.append(
                EdgeCaseItem(
                    priority="P1",
                    category="api_auth_error",
                    contract_name=contract_name,
                    citation=route.citation,
                    scenario=(
                        f"Send invalid `{route.request_model}` payload to `{contract_name}`"
                    ),
                    expected_behavior=(
                        "Returns 422 Unprocessable Entity with field-level validation details"
                    ),
                )
            )
    elif method == "GET" and "{" in route.path:
        items.append(
            EdgeCaseItem(
                priority="P1",
                category="api_auth_error",
                contract_name=contract_name,
                citation=route.citation,
                scenario=(
                    f"Request `{contract_name}` with a non-existent resource identifier"
                ),
                expected_behavior=(
                    "Returns 404 Not Found without leaking internal error details"
                ),
            )
        )

    return items


def _build_telemetry_item(telemetry: TelemetryContract) -> EdgeCaseItem:
    """Generate a telemetry verification edge case for a TelemetryContract."""
    if telemetry.properties:
        props_text = ", ".join(telemetry.properties)
        scenario = (
            f"Trigger `{telemetry.event_name}` ({telemetry.source_kind}) "
            f"and verify properties: {props_text}"
        )
        expected_behavior = (
            f"Emits `{telemetry.event_name}` with required properties ({props_text})"
        )
    else:
        scenario = f"Trigger `{telemetry.event_name}` ({telemetry.source_kind})"
        expected_behavior = f"Emits `{telemetry.event_name}` event reliably"

    return EdgeCaseItem(
        priority="P2",
        category="telemetry",
        contract_name=telemetry.event_name,
        citation=telemetry.citation,
        scenario=scenario,
        expected_behavior=expected_behavior,
    )


def _format_checklist_markdown(
    *,
    repo_root: str,
    items: list[EdgeCaseItem],
    p0_count: int,
) -> str:
    """Render an EdgeCaseChecklist as a Markdown checklist."""
    p1_count = sum(1 for item in items if item.priority == "P1")
    p2_count = sum(1 for item in items if item.priority == "P2")

    lines = [
        "## PMCursor Edge-Case Checklist",
        "",
        f"- **Repository:** `{repo_root}`",
        f"- **Total items:** {len(items)} (P0: {p0_count}, P1: {p1_count}, P2: {p2_count})",
        "",
    ]

    if not items:
        lines.append("No edge-case items generated.")
    else:
        for item in items:
            lines.append(
                f"- [ ] **[{item.priority}]** [{item.category}] **{item.contract_name}**: "
                f"{item.scenario} — {item.expected_behavior} (`{item.citation}`)"
            )

    return "\n".join(lines) + "\n"


def generate_edge_case_checklist(
    repo_map: RepoMap,
    *,
    prd_markdown: str | None = None,
    repo_root: Path | None = None,
) -> EdgeCaseChecklist:
    """Generate a codebase-cited edge-case and QA checklist from a RepoMap."""
    items: list[EdgeCaseItem] = []

    if prd_markdown is not None:
        drift_report = check_spec_drift(prd_markdown, repo_map, repo_root=repo_root)
        for finding in drift_report.findings:
            citation = finding.code_citation or finding.spec_reference
            items.append(
                EdgeCaseItem(
                    priority="P0",
                    category="spec_drift",
                    contract_name=finding.spec_reference,
                    citation=citation,
                    scenario=finding.message,
                    expected_behavior=finding.remediation,
                )
            )

    for model in repo_map.models:
        items.extend(_build_model_items(model))

    for route in repo_map.routes:
        items.extend(_build_route_items(route))

    for telemetry in repo_map.telemetry:
        items.append(_build_telemetry_item(telemetry))

    effective_root = str(repo_root) if repo_root is not None else repo_map.repo_root
    p0_count = sum(1 for item in items if item.priority == "P0")
    markdown = _format_checklist_markdown(
        repo_root=effective_root,
        items=items,
        p0_count=p0_count,
    )

    return EdgeCaseChecklist(
        repo_root=effective_root,
        total_items=len(items),
        p0_count=p0_count,
        items=items,
        markdown=markdown,
    )
