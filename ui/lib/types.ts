// TypeScript mirrors of the Pydantic response models in src/pmcursor/models.py,
// checklists.py, and api/server.py. Field names match the JSON wire format.

export type CompletionStatus =
  | "DONE"
  | "DONE_WITH_CONCERNS"
  | "BLOCKED"
  | "NEEDS_CONTEXT";

export type SeverityLevel = "critical" | "high" | "medium" | "low";

export type DriftCategory =
  | "fabricated_citation"
  | "missing_model"
  | "missing_field"
  | "type_mismatch"
  | "missing_route"
  | "method_mismatch"
  | "unindexed_adr"
  | "missing_telemetry"
  | "telemetry_property_mismatch";

export type TelemetrySourceKind =
  | "track_event"
  | "langfuse"
  | "bigquery"
  | "posthog"
  | "vercel_analytics";

export type EdgeCasePriority = "P0" | "P1" | "P2";

export type EdgeCaseCategory =
  | "schema_validation"
  | "api_auth_error"
  | "telemetry"
  | "spec_drift";

export interface FieldContract {
  name: string;
  type_annotation: string;
  required: boolean;
  line: number;
}

export interface ModelContract {
  name: string;
  file_path: string;
  line: number;
  base_classes: string[];
  fields: FieldContract[];
}

export interface RouteContract {
  method: string;
  path: string;
  function_name: string;
  file_path: string;
  line: number;
  request_model: string | null;
  response_model: string | null;
}

export interface TelemetryContract {
  event_name: string;
  source_kind: TelemetrySourceKind;
  properties: string[];
  file_path: string;
  line: number;
}

export interface ADRContract {
  adr_id: string;
  title: string;
  status: string;
  file_path: string;
  line: number;
}

export interface RepoMap {
  repo_root: string;
  models: ModelContract[];
  routes: RouteContract[];
  telemetry: TelemetryContract[];
  adrs: ADRContract[];
  indexed_files: string[];
}

export interface SpecAlignmentScore {
  overall_score: number;
  deterministic_score: number;
  workflow_score: number;
  has_acceptance_cards: boolean;
  has_rollback_section: boolean;
  has_out_of_scope_section: boolean;
  has_adr_references: boolean;
}

export interface DriftFinding {
  category: DriftCategory;
  severity: SeverityLevel;
  spec_reference: string;
  code_citation: string | null;
  message: string;
  remediation: string;
}

export interface DriftReport {
  prd_path: string;
  status: CompletionStatus;
  alignment_score: SpecAlignmentScore;
  total_spec_contracts: number;
  matched_contracts: number;
  total_citations_checked: number;
  fabricated_citations_count: number;
  findings: DriftFinding[];
}

export interface EdgeCaseItem {
  priority: EdgeCasePriority;
  category: EdgeCaseCategory;
  contract_name: string;
  citation: string;
  scenario: string;
  expected_behavior: string;
}

export interface EdgeCaseChecklist {
  repo_root: string;
  total_items: number;
  p0_count: number;
  items: EdgeCaseItem[];
  markdown: string;
}
