# Changelog

All notable changes to PMCursor are documented in this file.

## [Unreleased]

### Added

- Added the FastAPI webhook server in `api/server.py` and the composite GitHub Action in `.github/actions/pmcursor-drift/action.yml`.
- Added Linear and Jira ticket auditing in `src/pmcursor/tickets.py` with the `pmcursor ticket-sync` CLI subcommand and `pmcursor serve` to launch the API server.
- Added the codebase-cited edge-case checklist generator in `src/pmcursor/checklists.py` with the `pmcursor checklist` CLI subcommand.
- Added `/v1/tickets/audit`, `/v1/checklist`, and `/v1/canvas` endpoints to the FastAPI server.
- Added `POST /v1/webhooks/linear`, `POST /v1/webhooks/jira`, `verify_linear_signature`, `verify_jira_signature`, and top-level `pmcursor` package exports (`audit_ticket_against_repo`, `generate_edge_case_checklist`).
- Added Prisma (`.prisma`) and GraphQL (`.graphql`/`.gql`) contract indexing in `src/pmcursor/indexer.py`.
- Added `step-summary` and `checklist` inputs to `.github/actions/pmcursor-drift/action.yml` to publish Markdown drift reports and edge-case checklists to GitHub Step Summary.
- Added optional `EdgeCaseChecklist` rendering in `render_split_pane_canvas` (`web/canvas.py`) with HTML escaping for all checklist fields.
- Added the release notes synthesizer and PRD scope coverage matrix in `src/pmcursor/release_notes.py` (`ScopeCoverageReport`, `pmcursor release-notes`, and `POST /v1/release-notes`).
- Added the MCP server and incremental repository cache in `src/pmcursor/mcp_server.py` (`PMCursorMCPServer`, `RepoIndexCache`, `pmcursor mcp`) alongside `.mcp.json` for IDE/agent integration.
- Added the project milestone roadmap in `docs/ROADMAP.md`, including the `M15` Feature Flag & Rollout Contract Verification milestone expansion.

### Security & Hardening

- Added a server bind guard requiring `PMCURSOR_API_TOKEN` when binding to non-loopback hosts, `WEB_CONCURRENCY` worker configuration, graceful CLI handling when `pmcursor[server]` extras are not installed, and Markdown table cell escaping.

## v0.1.0 (2026-11-25)

### Added

- Implemented `EXP-1` contract extractors for Zod schemas, Next.js App Router routes, OpenAPI specifications, and SQL DDL tables in `src/pmcursor/indexer.py`, alongside Pydantic models, FastAPI routes, and architecture decision records.
- Implemented `EXP-2` automated PRD repair via `fix_prd_markdown` in `src/pmcursor/drift.py` and the `pmcursor fix-prd` CLI subcommand.
- Implemented `EXP-3` pull request impact analysis via `verify_github_signature` and `compute_pr_impact` in `api/__init__.py` and the `pmcursor pr-impact` CLI subcommand.
- Implemented `EXP-4` telemetry contract indexing for `track_event`, PostHog, Vercel Analytics, Langfuse, and BigQuery, plus PRD `telemetry:` drift checks.
- Implemented `EXP-5` interactive split-pane HTML spec canvas generation via `render_split_pane_canvas` in `web/canvas.py` and the `pmcursor canvas` CLI subcommand.
- Added CLI subcommands in `src/pmcursor/cli.py`: `index`, `drift`, `fix-prd`, `pr-impact`, `canvas`, `validate-plugin`, and `eval`.
- Packaged PMCursor as a Cursor and Claude plugin with `.cursor-plugin/plugin.json`, `.claude-plugin/plugin.json`, `rules/`, `skills/`, and `agents/`.

### Security

- Implemented `SEC-1` path containment within `repo_root`, `2MB` file size caps, and `(OSError, UnicodeDecodeError)` error handling in `src/pmcursor/indexer.py` and `src/pmcursor/drift.py`.

### Verification

- The test suite passed 10 of 10 tests via `PYTHONPATH=src:. pytest`.
- The evaluation benchmark reported 100.0% schema and route mismatch recall, 5 of 5, and 0 unflagged fabricated file citations, 2 of 2 caught, via `PYTHONPATH=src python3 -m pmcursor.cli eval --json`.
