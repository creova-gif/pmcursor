# Changelog

All notable changes to PMCursor are documented in this file.

## [Unreleased]

### Added

- Added GitHub App pull-request automation in `src/pmcursor/github_pr_automation.py`: when a `GitHubAppAuth` is configured, actionable `pull_request` webhook events (`opened`, `synchronize`, `reopened`, `ready_for_review`) queue a FastAPI background task that mints an installation token, streams the head-SHA tarball (50MB cap, safe `tarfile` extraction), indexes the tree, fetches the repo spec from candidate paths, computes PR impact, and posts a GitHub check run whose conclusion derives from the deterministic `DriftReport`. Pipeline failures post a `neutral` check run instead of failing silently. Disable with `PMCURSOR_GITHUB_APP_AUTO_RUN=0`; `PMCURSOR_GITHUB_API_BASE` targets GitHub Enterprise.
- Added a `ui` CI job (setup-node v7, `npm ci`, `tsc --noEmit`, `next build`).
- Added the interactive Next.js split-pane UI in `ui/` (Next.js 16 + React 19): `Workspace` client shell, `SpecPane` (editable Living PRD, severity-sorted findings table, edge-case checklist), `ContractsPane` (RepoMap browser for models/routes/telemetry/ADRs), `app/api/pmcursor/[...path]` server-side proxy (`PMCURSOR_API_URL`, `PMCURSOR_API_TOKEN` injected so no CORS is needed), and `lib/types.ts` TypeScript mirrors of the backend models.
- Added `POST /v1/index` returning a `RepoMap`, used by the UI's contracts pane.
- Added the installable GitHub App flow in `src/pmcursor/github_app.py` (`build_app_manifest`, `exchange_manifest_code` for the manifest-creation redirect `code`, `GitHubAppAuth` minting RS256-JWT installation tokens with a refresh-margin cache, `default_github_app` env wiring via `PMCURSOR_GITHUB_APP_ID` + `PMCURSOR_GITHUB_APP_PRIVATE_KEY`/`_PATH`) behind a new `pmcursor[github-app]` extra (`PyJWT[crypto]>=2.8`). New `pmcursor github-app manifest|convert|token` CLI subcommand; new `GET /v1/github-app/manifest`, `POST /v1/github-app/manifest/conversions`, and `POST /v1/github-app/installations/{installation_id}/token` endpoints (injectable via `create_app(github_app=...)`); the GitHub webhook now accepts `installation`, `installation_repositories`, and `installation_target` lifecycle events.
- Added live telemetry source connectors in `src/pmcursor/telemetry_connectors.py` (`TelemetryConnector` protocol, `LangfuseConnector` via the Langfuse public observations API with basic auth and pagination, `BigQueryConnector` behind a new `pmcursor[bigquery]` extra, `fetch_telemetry_events`, `ConnectorFetchError`, `TelemetryConnectorResult`). `telemetry-verify` now accepts `--source langfuse|bigquery` with `--limit` as an alternative to `--events-file`, and `POST /v1/telemetry/verify` accepts `source` + `limit` in place of `events`. Langfuse outbound URLs reuse the publisher's SSRF guard; BigQuery table/column identifiers are whitelist-validated before query construction.
- Added Claude-powered PM drift summaries in `src/pmcursor/llm.py` (`PMDriftSummary`, `summarize_drift_report`, `LLMClient` protocol, `AnthropicLLMClient`, `default_llm_client`) behind a new `pmcursor[llm]` extra (`anthropic>=2.0`), the `pmcursor summarize` CLI subcommand (with `--offline` and `--json`), and the `POST /v1/summarize` API endpoint. Ship recommendation, top risks, and suggested spec edits are always computed deterministically; Claude writes only the narrative and falls back to a template on any failure.
- Added `create_app(llm_client=...)` injection so API tests and embedders can supply a stub `LLMClient`.
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
- Added multi-repo contract federation in `src/pmcursor/federation.py` (`merge_repo_maps`, `index_federated_repos`) with the `pmcursor federate` CLI subcommand.
- Added feature flag & rollout contract verification in `src/pmcursor/feature_flags.py` (`extract_feature_flags`, `audit_feature_flags_and_rollout`, `FlagAuditReport`), the `pmcursor flags` CLI subcommand, and the `POST /v1/flags/audit` API endpoint.
- Added runtime telemetry sample verification in `src/pmcursor/telemetry_verify.py` (`verify_telemetry_samples`, `ObservedTelemetryEvent`, `TelemetryDriftItem`, `TelemetryVerificationReport`), the `pmcursor telemetry-verify` CLI subcommand, and the `POST /v1/telemetry/verify` API endpoint.
- Added bi-directional comment publishing in `src/pmcursor/publisher.py` (`publish_github_pr_comment`, `publish_linear_comment`, `publish_jira_comment`, `PublishResult`) and the org alignment dashboard via `pmcursor dashboard` and `GET /v1/dashboard`.
- Added the project milestone roadmap in `docs/ROADMAP.md` (`M1`–`M16` completed), `CONTRIBUTING.md`, and GitHub issue/PR templates under `.github/`.
- Added `GET /readyz` readiness probe (reporting cached repository count) and `X-Request-ID` / `X-Process-Time-Ms` observability middleware in `api/server.py`.
- Added production container packaging (`Dockerfile`, `.dockerignore`), [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), and a Python `3.11`/`3.12` CI test matrix in `.github/workflows/ci.yml`.
- Added the `pmcursor doctor` diagnostic CLI subcommand in `src/pmcursor/cli.py` (with `--repo` and `--json`, reporting Python version, server extra availability, plugin manifest validity, and boolean secret configuration status without printing secret values).
- Added `POST /v1/cache/clear` in `api/server.py` to clear cached repository indexes.
- Added exponential-backoff retries on HTTP `429`, `5xx`, and `URLError` failures in `src/pmcursor/publisher.py`.
- Added the `pmcursor publish` CLI subcommand and `POST /v1/publish` endpoint in `api/server.py` to publish comments to GitHub PRs, Linear issues, and Jira issues.
- Added `PMCURSOR_CORS_ORIGINS` configuration for allowed CORS origins in `api/server.py`.
- Added `tests/test_release_consistency.py` to verify version parity across `pyproject.toml`, `.cursor-plugin/plugin.json`, and `.claude-plugin/plugin.json` and non-empty release files.
- Added `.env.example` and `docker-compose.yml` for local Docker Compose container startup and environment configuration.
- Added `.github/workflows/release.yml` for tag-driven release automation and `SECURITY.md` for vulnerability reporting policy.
- Added SARIF 2.1.0 export in `src/pmcursor/sarif.py` (`drift_report_to_sarif`) and the `--sarif` flag on `pmcursor drift` for GitHub Code Scanning integration.
- Added `.github/CODEOWNERS`, `.github/dependabot.yml`, and `.github/workflows/security.yml` for repository ownership, automated dependency updates, and CI security scanning.
- Added [docs/API_REFERENCE.md](docs/API_REFERENCE.md) documenting FastAPI authentication, error codes, security headers, HTTP endpoints, and MCP stdio tools.
- Added `run_performance_benchmark` in `evals/benchmark.py` for throughput and latency benchmarking.
- Added `pmcursor_rate_limited_total` and `pmcursor_webhook_duplicates_total` Prometheus counters on `GET /metrics` in `api/server.py`.
- Added `pytest-cov` with a `>= 80%` coverage gate (`--cov-fail-under=80`) in `.github/workflows/ci.yml`.
- Added responsive mobile layout (`@media (max-width: 900px)`) and clear-filter UX in `web/canvas.py`.

### Changed

- Extracted `build_parser` into `src/pmcursor/_cli_parser.py` for maintainability.
- Modularized multi-stack contract indexing into `src/pmcursor/_multistack_indexer.py`.

### Accessibility

- Added WCAG 2.1 AA accessibility enhancements in `web/canvas.py`, including semantic landmarks, skip-to-workspace navigation, `:focus-visible` focus rings, and live filter announcements.

### Performance

- Integrated `RepoIndexCache` in `api/server.py` to cache repository contract indexes across API requests.

### Security

- Added `_validate_outbound_url` SSRF guard in `src/pmcursor/publisher.py` enforcing `https://` and blocking embedded credentials, localhost, link-local, and RFC1918 private IPs by default (`allow_private_urls=False`).
- Added `_SlidingWindowRateLimiter` (`PMCURSOR_RATE_LIMIT_PER_MIN`) in `api/server.py` returning HTTP `429` with `Retry-After` when exceeded (`/health` and `/readyz` probes exempt), with bounded `max_clients=10_000` LRU eviction and opt-in `PMCURSOR_TRUST_PROXY` support for `X-Forwarded-For` client IP resolution behind reverse proxies.
- Added `_DeliveryDeduplicator` in `api/server.py` to deduplicate replayed webhooks via `X-GitHub-Delivery`, `Linear-Delivery`, and `X-Atlassian-Webhook-Identifier` (Jira) headers.
- Added security response headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`) in `api/server.py`.
- Added `threading.RLock` locking to `RepoIndexCache` in `src/pmcursor/mcp_server.py` for thread-safe concurrent access.
- Added `metrics_lock` synchronization for thread-safe request metrics updates in `api/server.py`.
- Added a `2MB` webhook payload cap returning HTTP `413` on oversized webhook requests in `api/server.py`.
- Added a server bind guard requiring `PMCURSOR_API_TOKEN` when binding to non-loopback hosts, `WEB_CONCURRENCY` worker configuration, graceful CLI handling when `pmcursor[server]` extras are not installed, and Markdown table cell escaping.

### Fixed

- Made `tests/test_repo_governance.py` action-version assertions version-agnostic so Dependabot action bumps no longer break the suite.

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
