# PMCursor API & MCP Reference

This document describes the HTTP API exposed by [api/server.py](../api/server.py) and the JSON-RPC stdio tools exposed by [src/pmcursor/mcp_server.py](../src/pmcursor/mcp_server.py).

## Authentication

### Bearer & Token Header Authentication

When `PMCURSOR_API_TOKEN` is configured, protected `/v1/*` endpoints require a valid token passed via either header (compared using constant-time `hmac.compare_digest`):

- `Authorization: Bearer <PMCURSOR_API_TOKEN>`
- `X-PMCursor-Token: <PMCURSOR_API_TOKEN>`

When `PMCURSOR_ORG_STORE` is configured (or `create_app(org_registry=...)`), per-organization API keys (`pmk_...`, issued via `pmcursor orgs`) authenticate the same way — either header — and bind the resolved `org_id` to the request. `GET /v1/whoami` reports which credential resolved (`admin`, `org-key`, or `open`). Org keys are stored as SHA-256 hashes; `pmcursor orgs` prints the plaintext once at issue time.

Org keys get `403 Forbidden` on deployment-level endpoints (`POST /v1/cache/clear`, all `/v1/github-app/*` routes) — those are admin-only. Rate limits bucket per-tenant (`org:<org_id>`) when an org key resolves, otherwise per-IP; the repository index cache is likewise namespaced per org.

### Webhook HMAC Signatures

Incoming webhook endpoints verify request bodies using HMAC-SHA256 signatures and deduplicate replayed deliveries:

| Endpoint | Signature Header | Secret Environment Variable | Delivery Deduplication Header |
|:---|:---|:---|:---|
| `POST /v1/webhooks/github` | `X-Hub-Signature-256` | `PMCURSOR_WEBHOOK_SECRET` | `X-GitHub-Delivery` |
| `POST /v1/webhooks/linear` | `Linear-Signature` | `PMCURSOR_LINEAR_WEBHOOK_SECRET` | `Linear-Delivery` |
| `POST /v1/webhooks/jira` | `X-Hub-Signature` | `PMCURSOR_JIRA_WEBHOOK_SECRET` (falls back to `PMCURSOR_API_TOKEN` Bearer/header auth when unset) | `X-Atlassian-Webhook-Identifier` |

## Standard Error Codes

| Status Code | Meaning | Typical Cause |
|:---|:---|:---|
| `401 Unauthorized` | Authentication failed | Missing/invalid `PMCURSOR_API_TOKEN` or invalid webhook HMAC signature |
| `403 Forbidden` | Workspace boundary violation | `repo_root` resolves outside `allowed_workspace_root` |
| `404 Not Found` | Resource missing | `repo_root` directory does not exist |
| `413 Content Too Large` | Payload limit exceeded | Request or webhook body exceeds `2MB` (`2_097_152` bytes) |
| `422 Unprocessable Entity` | Validation or decoding error | Invalid JSON/form payload, Pydantic validation failure, or invalid publish request |
| `429 Too Many Requests` | Rate limit exceeded | Exceeded `PMCURSOR_RATE_LIMIT_PER_MIN` (includes `Retry-After: 60`; `/health` and `/readyz` exempt) |
| `502 Bad Gateway` | Upstream publish failure | Downstream GitHub, Linear, or Jira API error (`RuntimeError` / `OSError`) |

## Security & Observability Response Headers

All HTTP responses include the following headers from `request_context_middleware`:

- `X-Request-ID`: Echoes incoming `X-Request-ID` or generates a UUIDv4 correlation ID.
- `X-Process-Time-Ms`: Request processing duration in milliseconds.
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`

## HTTP Endpoints

| Method | Path | Auth | Description | Response Type |
|:---|:---|:---|:---|:---|
| `GET` | `/health` | None | Liveness probe (`{"status": "ok"}`) | `application/json` |
| `GET` | `/readyz` | None | Readiness probe reporting `cached_repos` count | `application/json` |
| `GET` | `/v1/whoami` | Token | Resolve the presented credential (`admin`, `org-key` + `org_id`, or `open` when no auth is configured) | `application/json` |
| `GET` | `/metrics` | Admin | Prometheus counters/gauges (`pmcursor_http_requests_total`, `pmcursor_http_errors_total`, `pmcursor_rate_limited_total`, `pmcursor_webhook_duplicates_total`, `pmcursor_repo_cache_entries`, `pmcursor_repo_cache_hits_total`, `pmcursor_repo_cache_misses_total`) | `text/plain; version=0.0.4` |
| `POST` | `/v1/drift/audit` | Token | Audit PRD markdown against indexed repository contracts | `DriftReport` (JSON) |
| `POST` | `/v1/summarize` | Token | Summarize a drift audit into a PM-facing narrative (`offline: true` forces the deterministic template) | `PMDriftSummary` (JSON) |
| `POST` | `/v1/tickets/audit` | Token | Audit a Linear or Jira ticket against repository contracts | `TicketSyncReport` (JSON) |
| `POST` | `/v1/checklist` | Token | Generate a codebase-cited edge-case checklist | `EdgeCaseChecklist` (JSON) |
| `POST` | `/v1/canvas` | Token | Render an interactive split-pane HTML spec canvas | `text/html` |
| `POST` | `/v1/release-notes` | Token | Synthesize diff-grounded release notes and PRD scope coverage | `ReleaseNotesReport` (JSON) |
| `POST` | `/v1/flags/audit` | Token | Audit PRD feature-flag declarations and rollout/rollback readiness | `FlagAuditReport` (JSON) |
| `POST` | `/v1/telemetry/verify` | Token | Verify observed runtime telemetry samples against indexed contracts (body: `events` XOR `source` + `limit`) | `TelemetryVerificationReport` (JSON) |
| `POST` | `/v1/index` | Token | Index a repository into a `RepoMap` (models, routes, telemetry, ADRs, indexed files) | `RepoMap` (JSON) |
| `GET` | `/v1/github-app/manifest` | Token | Build a GitHub App creation manifest (`webhook_url` required) | manifest JSON |
| `POST` | `/v1/github-app/manifest/conversions` | Token | Exchange an app-manifest `code` for app credentials | `GitHubAppCredentials` (JSON, sensitive) |
| `POST` | `/v1/github-app/installations/{installation_id}/token` | Token | Mint an installation access token (requires `pmcursor[github-app]` + app env config) | `GitHubInstallationToken` (JSON) |
| `GET` | `/v1/dashboard` | Token | Compute organization alignment summary (`repo_root`, `prd_path` query params) | `OrgDashboardSummary` (JSON) |
| `POST` | `/v1/publish` | Token | Publish a comment to a GitHub PR, Linear issue, or Jira issue | `PublishResult` (JSON) |
| `POST` | `/v1/cache/clear` | Token | Clear all cached repository index entries | `application/json` |
| `POST` | `/v1/webhooks/github` | HMAC | Handle GitHub webhook events (`ping`, `pull_request`, `merge_group`, `check_run`, installation lifecycle, or `PRImpactReport` audit). When a `GitHubAppAuth` is configured, eligible events queue a background drift audit that posts a check run via the installation token; failures also upsert a marker comment on the PR (`PMCURSOR_GITHUB_APP_AUTO_RUN=0` / `PMCURSOR_GITHUB_APP_PR_COMMENTS=0` to disable) | `PRImpactReport` / JSON |
| `POST` | `/v1/webhooks/linear` | HMAC | Handle Linear issue webhooks and return a `TicketSyncReport` | `TicketSyncReport` / JSON |
| `POST` | `/v1/webhooks/jira` | HMAC / Token | Handle Jira issue webhooks and return a `TicketSyncReport` | `TicketSyncReport` / JSON |

## MCP Stdio Server Tools

Start the MCP server via `pmcursor mcp` (configured in [.mcp.json](../.mcp.json)). It communicates over JSON-RPC 2.0 stdio and exposes the following 7 tools:

| Tool | Required Arguments | Optional Arguments | Description |
|:---|:---|:---|:---|
| `pmcursor_index` | `repo_root` | — | Index a repository's models, routes, telemetry events, and ADRs into a `RepoMap`. |
| `pmcursor_drift` | `repo_root`, `prd_markdown` | `prd_path` | Check a PRD markdown specification for drift against the indexed codebase. |
| `pmcursor_checklist` | `repo_root` | `prd_markdown` | Generate a codebase-cited edge-case and QA checklist from an indexed repository. |
| `pmcursor_ticket_sync` | `repo_root`, `ticket_id`, `title`, `description` | `provider` (`linear` \| `jira`) | Audit a Linear or Jira ticket against the indexed codebase. |
| `pmcursor_release_notes` | `repo_root`, `prd_markdown`, `diff_text` | `prd_path`, `version` | Generate release notes and PRD scope coverage from a unified git diff. |
| `pmcursor_flags` | `prd_markdown` | `repo_root` | Audit PRD feature-flag declarations and rollout/rollback readiness. |
| `pmcursor_telemetry_verify` | `events` | `repo_root` | Verify observed runtime telemetry event samples against indexed `TelemetryContract` definitions. |
