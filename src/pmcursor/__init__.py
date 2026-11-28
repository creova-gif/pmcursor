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
from pmcursor.llm import (
    AnthropicLLMClient,
    LLMClient,
    LLMUnavailableError,
    PMDriftSummary,
    default_llm_client,
    summarize_drift_report,
)
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
from pmcursor.publisher import (
    PublishResult,
    publish_github_pr_comment,
    publish_jira_comment,
    publish_linear_comment,
)
from pmcursor.release_notes import (
    ReleaseNotesEntry,
    ReleaseNotesReport,
    ScopeCoverageReport,
    compute_scope_coverage,
    generate_release_notes_and_coverage,
)
from pmcursor.sarif import drift_report_to_sarif
from pmcursor.telemetry_verify import (
    ObservedTelemetryEvent,
    TelemetryDriftItem,
    TelemetryVerificationReport,
    verify_telemetry_samples,
)
from pmcursor.tickets import (
    TicketProvider,
    TicketSyncReport,
    audit_ticket_against_repo,
)

__all__ = [
    "ADRContract",
    "AnthropicLLMClient",
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
    "LLMClient",
    "LLMUnavailableError",
    "ModelContract",
    "ObservedTelemetryEvent",
    "PMCursorMCPServer",
    "PMDriftSummary",
    "PRImpactItem",
    "PRImpactReport",
    "PluginValidationResult",
    "PublishResult",
    "ReleaseNotesEntry",
    "ReleaseNotesReport",
    "RepoIndexCache",
    "RepoMap",
    "RouteContract",
    "ScopeCoverageReport",
    "SpecAlignmentScore",
    "TelemetryContract",
    "TelemetryDriftItem",
    "TelemetrySourceKind",
    "TelemetryVerificationReport",
    "TicketProvider",
    "TicketSyncReport",
    "audit_feature_flags_and_rollout",
    "audit_ticket_against_repo",
    "check_spec_drift",
    "compute_scope_coverage",
    "default_llm_client",
    "drift_report_to_sarif",
    "extract_feature_flags",
    "fix_prd_markdown",
    "format_drift_report_markdown",
    "generate_edge_case_checklist",
    "generate_release_notes_and_coverage",
    "healthcheck",
    "index_federated_repos",
    "index_repository",
    "merge_repo_maps",
    "publish_github_pr_comment",
    "publish_jira_comment",
    "publish_linear_comment",
    "run_eval_benchmark",
    "run_mcp_server",
    "summarize_drift_report",
    "validate_plugin_manifests",
    "verify_telemetry_samples",
]


def healthcheck() -> str:
    return "ok"
