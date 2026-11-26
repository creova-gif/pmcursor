# Threat Model
- **Assets:** API credentials, tenant data (`org_id`), execution logs, downstream tools.
- **Trust Boundaries:** Client -> Gateway -> Sandbox -> Secret Manager / Storage.
- **Mitigations:** Strict schema validation, `org_id` tenant scoping, GCP Secret Manager + OIDC, `gitleaks` in CI.
- **Server Bind Guard (`api/server.py`):** `PMCURSOR_API_TOKEN` is required when binding outside loopback hosts (`127.0.0.1`, `localhost`, `::1`).
- **Webhook Authentication & Workspace Containment (`api/server.py`):** Linear webhooks authenticate via `Linear-Signature` (HMAC-SHA256, `PMCURSOR_LINEAR_WEBHOOK_SECRET`), Jira webhooks authenticate via `X-Hub-Signature` (HMAC-SHA256, `PMCURSOR_JIRA_WEBHOOK_SECRET`) or Bearer `PMCURSOR_API_TOKEN`, and `_resolve_allowed_repo_root` enforces containment within `allowed_workspace_root`.
- **Markdown Table Injection Mitigation (`src/pmcursor/tickets.py`):** `_escape_markdown_cell` normalizes line breaks and escapes `|` characters to prevent table-injection and row breaking in generated ticket comments.
