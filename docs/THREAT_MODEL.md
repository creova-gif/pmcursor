# Threat Model

- **Assets:** Admin API token, org API keys (`pmk_` hashes), GitHub App private key + installation tokens, webhook secrets, repository contents under the workspace root, audit logs, downstream integrations (Linear/Jira/GitHub).
- **Trust Boundaries:** Internet client → API server → filesystem (workspace, org store) → outbound integrations (GitHub, Langfuse, BigQuery, LLM, ticket trackers).
- **Identity model:** `PMCURSOR_API_TOKEN` is the deployment admin credential; `pmk_*` org keys authenticate a single org with least-privilege scope; HMAC webhook secrets authenticate provider deliveries; the GitHub App authenticates via RS256 JWT + installation tokens.

## Mitigations

- **Server Bind Guard (`api/server.py`):** `PMCURSOR_API_TOKEN` is required when binding outside loopback hosts (`127.0.0.1`, `localhost`, `::1`).
- **Org API Keys (`src/pmcursor/tenancy.py`):** `pmk_` keys are shown once, persisted only as SHA-256 hashes in a `0600` store, resolved with `hmac.compare_digest`, revocable by id, and metered via `last_used_at`. Atomic tempfile+`os.replace` writes.
- **Admin Gating:** Org keys receive `403` on deployment endpoints (`/v1/cache/clear`, `/v1/github-app/*`, `/metrics`); only the admin token (or open local mode) may call them.
- **Per-Tenant Isolation:** Rate limits bucket per-org (`org:<id>`, IP fallback); the repository index cache is namespaced `(scope, path)` so tenants never share cached `RepoMap`s.
- **Per-Org Workspace Roots:** Org-key requests must resolve under admin-registered `workspace_roots` (empty = deny all) layered under global `allowed_workspace_root` containment; denials emit `repo_root_denied` audit events.
- **Webhook Authentication, Workspace Containment & Replay Deduplication (`api/server.py`):** GitHub/Linear/Jira deliveries verify HMAC-SHA256 signatures (`X-Hub-Signature-256`, `Linear-Signature`, `X-Hub-Signature`; Jira falls back to bearer auth when unconfigured), delivery IDs deduplicate replays, and `_resolve_allowed_repo_root` enforces containment.
- **Rate Limiting:** `PMCURSOR_RATE_LIMIT_PER_MIN` sliding-window limiter returns `429` with `Retry-After` (`/health`, `/readyz` exempt); client IP from `X-Forwarded-For` only under opt-in `PMCURSOR_TRUST_PROXY`; bucket map bounded at 10k clients via LRU.
- **Outbound SSRF Protection (`src/pmcursor/publisher.py`):** `_validate_outbound_url` enforces `https://` and blocks embedded credentials, localhost/link-local/RFC1918 private ranges (`allow_private_urls=False`); Langfuse connector reuses the guard.
- **GitHub App PR Automation Caps (`github_pr_automation.py`):** Tarball downloads capped at 50 MB compressed plus cumulative extracted-size and member-count caps, `tarfile` data-filter extraction, diffs pinned to immutable event SHAs via the compare endpoint, installation tokens cached with refresh margin.
- **Security Audit Trail (`pmcursor.audit` logger):** `event=` lines for `auth_failure`, `admin_denied`, `repo_root_denied`, `rate_limited`, `webhook_signature_invalid`, and org lifecycle (`org_created`, `org_key_issued`, `org_key_revoked`, `org_roots_updated`); a test asserts credential material never reaches audit output.
- **Security Response Headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
- **Payload & Path Bounds:** 2 MB caps on webhook bodies and per-file indexing reads; workspace-root containment on all repo paths; BigQuery identifiers whitelist-validated before query construction.
- **Markdown Table Injection Mitigation (`src/pmcursor/tickets.py`):** `_escape_markdown_cell` normalizes line breaks and escapes `|` in generated ticket comments.
- **Non-Root Container:** The image runs as an unprivileged `pmcursor` user; the workspace bind-mounts read-only.
- **CI/CD Supply Chain:** All GitHub Actions pinned to commit SHAs (enforced by a repo-governance test), `ci.yml` runs with `contents: read`, weekly `gitleaks` + Ruff `S` rules + `pip-audit`, Dependabot across pip/npm/docker/github-actions.

## Known limits (residual risk)

- **Single-process state:** The rate limiter, index cache, deduplicator, and file-backed org store are per-process — run one uvicorn worker (`WEB_CONCURRENCY=1`) or accept weakened limits / lost store updates. Shared-state backends are a deliberate future migration.
- **File-backed registry:** `orgs.json` suits single-node deployments; concurrent writers on a shared filesystem are not safe. A database-backed registry belongs to the accounts layer.
- **Audit trail is log-based:** durability/routing is the deployment's log pipeline (stdout → collector), not a built-in store.
