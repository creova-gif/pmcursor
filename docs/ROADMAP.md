# PMCursor Roadmap

This roadmap tracks completed engineering milestones and upcoming platform capabilities for PMCursor.

## Completed Milestones

| Milestone | Name | Summary & Key Deliverables |
|:---|:---|:---|
| `M1` | Core AST Indexer & Drift Engine | Indexed Pydantic models, FastAPI routes, and ADRs in `src/pmcursor/indexer.py` and `src/pmcursor/models.py`; implemented spec-vs-code drift detection and `file:line` citation verification in `src/pmcursor/drift.py` (`pmcursor index`, `pmcursor drift`). |
| `M2` | Cursor & Claude Plugin Packaging & Eval Harness | Packaged PMCursor with `.cursor-plugin/plugin.json`, `.claude-plugin/plugin.json`, `skills/`, `agents/`, and `rules/`; added `src/pmcursor/plugin_validator.py` (`pmcursor validate-plugin`) and `src/pmcursor/eval_runner.py` (`pmcursor eval`). |
| `M3` | Multi-Stack Contract Extractors (`EXP-1` & `SEC-1`) | Added extractors for Zod schemas, Next.js App Router routes, OpenAPI specs, and SQL DDL tables alongside `repo_root` path containment and 2MB file size caps. |
| `M4` | Automated PRD Repair (`EXP-2`) | Implemented `fix_prd_markdown` in `src/pmcursor/drift.py` and `pmcursor fix-prd` to repair shifted `file:line` citations and mismatched field types. |
| `M5` | PR Impact Analysis (`EXP-3`) | Implemented `compute_pr_impact` and `verify_github_signature` in `api/__init__.py` and `pmcursor pr-impact` to map git diffs to impacted contracts and PRD references. |
| `M6` | Telemetry Contract Indexing (`EXP-4`) | Added telemetry event indexing for `track_event`, PostHog, Vercel Analytics, Langfuse, and BigQuery, plus PRD `telemetry:` drift checks. |
| `M7` | Interactive Split-Pane Spec Canvas (`EXP-5`) | Implemented `render_split_pane_canvas` in `web/canvas.py` and `pmcursor canvas` to generate an interactive HTML spec and contract inspector. |
| `M8` | FastAPI Webhook Server & Composite GitHub Action | Added `api/server.py` (`pmcursor serve`, `GET /health`, `POST /v1/drift/audit`, `POST /v1/webhooks/github`, `POST /v1/canvas`), non-loopback `PMCURSOR_API_TOKEN` bind guard, `WEB_CONCURRENCY` support, and `.github/actions/pmcursor-drift/action.yml`. |
| `M9` | Linear & Jira Ticket Auditing & Webhooks | Added `src/pmcursor/tickets.py` (`pmcursor ticket-sync`, `audit_ticket_against_repo`), `POST /v1/tickets/audit`, `POST /v1/webhooks/linear`, and `POST /v1/webhooks/jira` with HMAC-SHA256 signature verification. |
| `M10` | Codebase-Cited Edge-Case Checklists & Prisma/GraphQL Extractors | Added `src/pmcursor/checklists.py` (`pmcursor checklist`, `POST /v1/checklist`), `.prisma` and `.graphql`/`.gql` contract indexing, `EdgeCaseChecklist` canvas rendering, and `step-summary`/`checklist` GitHub Action inputs. |
| `M11` | Release Notes Synthesizer & Scope Coverage Matrix | Added `src/pmcursor/release_notes.py` (`ScopeCoverageReport`, `ReleaseNotesReport`, `pmcursor release-notes`, `POST /v1/release-notes`) to synthesize diff-grounded release notes and quantify PRD-to-repo scope coverage. |
| `M12` | MCP Server & Incremental Repo Cache | Added `src/pmcursor/mcp_server.py` (`PMCursorMCPServer`, `RepoIndexCache`, `run_mcp_server`, `pmcursor mcp`) and `.mcp.json` to expose PMCursor indexing, drift auditing, checklist generation, and release-notes synthesis over MCP with incremental repo caching. |
| `M14` | Multi-Repo Federation | Added `src/pmcursor/federation.py` (`merge_repo_maps`, `index_federated_repos`) and `pmcursor federate` to merge contracts across multiple repositories into a unified alias-prefixed `RepoMap`. |
| `M15` | Feature Flag & Rollout Contract Verification | Added `src/pmcursor/feature_flags.py` (`extract_feature_flags`, `audit_feature_flags_and_rollout`, `FlagAuditReport`), `pmcursor flags`, and `POST /v1/flags/audit` to index LaunchDarkly/Statsig/Unleash/generic flags and verify PRD rollout and rollback readiness. |

## Upcoming Milestones

### `M13` — Live Telemetry & Warehouse Verification (BigQuery / Langfuse / PostHog)
- Extend static telemetry contract indexing with optional read-only verification against live BigQuery schemas, Langfuse traces/prompts, and PostHog event definitions.
- Flag runtime schema/property mismatches between instrumented code, PRDs, and production analytics events.

### `M16` — **Bi-Directional GitHub PR & Linear/Jira Comment Bot + Org Alignment Dashboard**
- Enable bi-directional status synchronization and automated drift/flag-audit comments across GitHub pull requests and Linear/Jira issues.
- Provide an org-wide alignment dashboard aggregating spec drift, rollout readiness, and cross-repo contract health.
