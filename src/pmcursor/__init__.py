from __future__ import annotations

from pmcursor.checklists import (
    EdgeCaseCategory,
    EdgeCaseChecklist,
    EdgeCaseItem,
    EdgeCasePriority,
    generate_edge_case_checklist,
)
from pmcursor.drift import (
    check_spec_drift,
    fix_prd_markdown,
    format_drift_report_markdown,
)
from pmcursor.eval_runner import run_eval_benchmark
from pmcursor.indexer import index_repository
from pmcursor.models import (
    ADRContract,
    DriftFinding,
    DriftReport,
    EvalBenchmarkResult,
    FieldContract,
    FixPrdResult,
    ModelContract,
    PluginValidationResult,
    PRImpactItem,
    PRImpactReport,
    RepoMap,
    RouteContract,
    SpecAlignmentScore,
    TelemetryContract,
    TelemetrySourceKind,
)
from pmcursor.plugin_validator import validate_plugin_manifests
from pmcursor.release_notes import (
    ReleaseNotesEntry,
    ReleaseNotesReport,
    ScopeCoverageReport,
    compute_scope_coverage,
    generate_release_notes_and_coverage,
)
from pmcursor.tickets import (
    TicketProvider,
    TicketSyncReport,
    audit_ticket_against_repo,
)

__all__ = [
    "ADRContract",
    "DriftFinding",
    "DriftReport",
    "EdgeCaseCategory",
    "EdgeCaseChecklist",
    "EdgeCaseItem",
    "EdgeCasePriority",
    "EvalBenchmarkResult",
    "FieldContract",
    "FixPrdResult",
    "ModelContract",
    "PRImpactItem",
    "PRImpactReport",
    "PluginValidationResult",
    "ReleaseNotesEntry",
    "ReleaseNotesReport",
    "RepoMap",
    "RouteContract",
    "ScopeCoverageReport",
    "SpecAlignmentScore",
    "TelemetryContract",
    "TelemetrySourceKind",
    "TicketProvider",
    "TicketSyncReport",
    "audit_ticket_against_repo",
    "check_spec_drift",
    "compute_scope_coverage",
    "fix_prd_markdown",
    "format_drift_report_markdown",
    "generate_edge_case_checklist",
    "generate_release_notes_and_coverage",
    "healthcheck",
    "index_repository",
    "run_eval_benchmark",
    "validate_plugin_manifests",
]


def healthcheck() -> str:
    return "ok"
