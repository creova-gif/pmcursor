from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DriftCategory = Literal[
    "fabricated_citation",
    "missing_model",
    "missing_field",
    "type_mismatch",
    "missing_route",
    "method_mismatch",
    "unindexed_adr",
    "missing_telemetry",
    "telemetry_property_mismatch",
]

SeverityLevel = Literal["critical", "high", "medium", "low"]

CompletionStatus = Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT"]

TelemetrySourceKind = Literal[
    "track_event",
    "langfuse",
    "bigquery",
    "posthog",
    "vercel_analytics",
]


class FieldContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type_annotation: str
    required: bool = True
    line: int = Field(ge=1)


class ModelContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    file_path: str
    line: int = Field(ge=1)
    base_classes: list[str] = Field(default_factory=list)
    fields: list[FieldContract] = Field(default_factory=list)

    @property
    def citation(self) -> str:
        return f"{self.file_path}:{self.line}"


class RouteContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str
    path: str
    function_name: str
    file_path: str
    line: int = Field(ge=1)
    request_model: str | None = None
    response_model: str | None = None

    @property
    def citation(self) -> str:
        return f"{self.file_path}:{self.line}"


class TelemetryContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_name: str
    source_kind: TelemetrySourceKind
    properties: list[str] = Field(default_factory=list)
    file_path: str
    line: int = Field(ge=1)

    @property
    def citation(self) -> str:
        return f"{self.file_path}:{self.line}"


class ADRContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    adr_id: str
    title: str
    status: str
    file_path: str
    line: int = Field(ge=1)

    @property
    def citation(self) -> str:
        return f"{self.file_path}:{self.line}"


class RepoMap(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo_root: str
    models: list[ModelContract] = Field(default_factory=list)
    routes: list[RouteContract] = Field(default_factory=list)
    telemetry: list[TelemetryContract] = Field(default_factory=list)
    adrs: list[ADRContract] = Field(default_factory=list)
    indexed_files: list[str] = Field(default_factory=list)


class DriftFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: DriftCategory
    severity: SeverityLevel
    spec_reference: str
    code_citation: str | None = None
    message: str
    remediation: str


class SpecAlignmentScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall_score: int = Field(ge=0, le=100)
    deterministic_score: int = Field(ge=0, le=100)
    workflow_score: int = Field(ge=0, le=100)
    has_acceptance_cards: bool
    has_rollback_section: bool
    has_out_of_scope_section: bool
    has_adr_references: bool


class DriftReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    prd_path: str
    status: CompletionStatus
    alignment_score: SpecAlignmentScore
    total_spec_contracts: int = Field(ge=0)
    matched_contracts: int = Field(ge=0)
    total_citations_checked: int = Field(ge=0)
    fabricated_citations_count: int = Field(ge=0)
    findings: list[DriftFinding] = Field(default_factory=list)


class FixPrdResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    prd_path: str
    updated_markdown: str
    fixed_citations_count: int = Field(ge=0)
    fixed_types_count: int = Field(ge=0)
    applied: bool = False


class PRImpactItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_kind: Literal["model", "route", "telemetry", "adr"]
    name: str
    citation: str
    referenced_in_prd: bool


class PRImpactReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    prd_path: str
    org_id: str = "default"
    touched_contracts: list[PRImpactItem] = Field(default_factory=list)
    impacted_prd_references: list[str] = Field(default_factory=list)
    drift_report: DriftReport
    markdown_comment: str


class PluginValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    plugin_name: str
    version: str
    errors: list[str] = Field(default_factory=list)
    checked_components: list[str] = Field(default_factory=list)


class EvalBenchmarkResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    seeded_mismatches: int = Field(ge=0)
    detected_mismatches: int = Field(ge=0)
    recall: float = Field(ge=0.0, le=1.0)
    seeded_fabricated_citations: int = Field(ge=0)
    detected_fabricated_citations: int = Field(ge=0)
    unflagged_fabricated_citations: int = Field(ge=0)
    alignment_score: int = Field(ge=0, le=100)
