from __future__ import annotations

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

__all__ = [
    "ADRContract",
    "DriftFinding",
    "DriftReport",
    "EvalBenchmarkResult",
    "FieldContract",
    "FixPrdResult",
    "ModelContract",
    "PRImpactItem",
    "PRImpactReport",
    "PluginValidationResult",
    "RepoMap",
    "RouteContract",
    "SpecAlignmentScore",
    "TelemetryContract",
    "TelemetrySourceKind",
    "check_spec_drift",
    "fix_prd_markdown",
    "format_drift_report_markdown",
    "healthcheck",
    "index_repository",
    "run_eval_benchmark",
    "validate_plugin_manifests",
]


def healthcheck() -> str:
    return "ok"
