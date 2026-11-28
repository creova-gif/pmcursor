# Architecture Decision Records

Non-trivial design choices for PMCursor are recorded here per `AGENTS.md`. Use
`000-template.md` for new entries and number them sequentially.

| ADR | Decision |
|-----|----------|
| [001](001-contract-first-repo-indexing.md) | Contract-first repository indexing |
| [002](002-cursor-plugin-and-gstack-skill-architecture.md) | Cursor plugin and GStack skill architecture |
| [003](003-fastapi-webhook-server-and-github-action.md) | FastAPI webhook server and composite GitHub Action |
| [004](004-github-app-pull-request-automation.md) | GitHub App pull-request automation pipeline |
| [005](005-pr-automation-merge-queue-rerun-and-comments.md) | PR automation — merge queue, check-run reruns, and failure comments |
| [006](006-team-tenancy-org-registry-and-org-api-keys.md) | Team tenancy — org registry and per-org API keys |
| [007](007-per-tenant-isolation-admin-gating-scoped-rate-limits-and-caches.md) | Per-tenant isolation — admin gating, scoped rate limits, scoped caches |
| [008](008-metrics-auth-and-deployment-hygiene.md) | Metrics endpoint auth and deployment hygiene |
| [009](009-security-audit-event-logging.md) | Security audit event logging |
| [010](010-per-org-workspace-roots.md) | Per-org workspace roots — least-privilege repo access for org keys |
| [ADR-011](011-sqlite-org-registry-backend.md) | SQLite org-registry backend for multi-writer deployments |
