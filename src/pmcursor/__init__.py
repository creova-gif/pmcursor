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
from pmcursor.feature_flags import (
    FeatureFlagContract,
    FeatureFlagProvider,
    FlagAuditReport,
    audit_feature_flags_and_rollout,
    extract_feature_flags,
)
from pmcursor.federation import index_federated_repos, merge_repo_maps
from pmcursor.indexer import index_repository
from pmcursor.mcp_server import (
    PMCursorMCPServer,
    RepoIndexCache,
    run_mcp_server,
)
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
    "FeatureFlagContract",
    "FeatureFlagProvider",
    "FieldContract",
    "FixPrdResult",
    "FlagAuditReport",
    "ModelContract",
    "PMCursorMCPServer",
    "PRImpactItem",
    "PRImpactReport",
    "PluginValidationResult",
    "ReleaseNotesEntry",
    "ReleaseNotesReport",
    "RepoIndexCache",
    "RepoMap",
    "RouteContract",
    "ScopeCoverageReport",
    "SpecAlignmentScore",
    "TelemetryContract",
    "TelemetrySourceKind",
    "TicketProvider",
    "TicketSyncReport",
    "audit_feature_flags_and_rollout",
    "audit_ticket_against_repo",
    "check_spec_drift",
    "compute_scope_coverage",
    "extract_feature_flags",
    "fix_prd_markdown",
    "format_drift_report_markdown",
    "generate_edge_case_checklist",
    "generate_release_notes_and_coverage",
    "healthcheck",
    "index_federated_repos",
    "index_repository",
    "merge_repo_maps",
    "run_eval_benchmark",
    "run_mcp_server",
    "validate_plugin_manifests",
]


def healthcheck() -> str:
    return "ok"
