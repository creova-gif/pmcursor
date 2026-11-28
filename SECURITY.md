# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.2.x   | Yes       |
| 0.1.x   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in `pmcursor`, please report it privately using **GitHub Security Advisories** ("Report a vulnerability" in the repository's Security tab).

- **Do not** open a public GitHub issue, pull request, or discussion for undisclosed vulnerabilities.
- We aim to provide an initial response within **48 hours** of receiving a report, along with an assessment and remediation timeline.

## Built-in Security Controls

`pmcursor` includes the following defense-in-depth controls:

- **SSRF Guard (`src/pmcursor/publisher.py`):** Outbound publish targets are validated against private, loopback, link-local, and metadata IP ranges before requests are dispatched.
- **Path Containment & Size Limits (`indexer.py`, `api/server.py`):** Repository indexing and API file operations enforce root path containment and a 2 MB per-file read/index cap to prevent path traversal and memory exhaustion.
- **Webhook Authentication & Deduplication:** Incoming GitHub/Linear/Jira webhook deliveries are verified using HMAC-SHA256 signatures and tracked for delivery deduplication to prevent spoofing and replay.
- **API Authentication & Bind Guard:** Non-loopback API server binds require `PMCURSOR_API_TOKEN` to be configured, preventing unauthenticated network exposure.
- **Per-Org API Keys (`src/pmcursor/tenancy.py`):** Org keys (`pmk_...`) are stored as SHA-256 hashes (plaintext shown once at issue), resolved with constant-time comparison, revocable by id, and bind `org_id` for per-tenant rate-limit buckets and index-cache scopes.
- **Per-Org Workspace Roots:** Org keys can only reach repos under admin-registered `workspace_roots` (`pmcursor orgs add-root`); empty roots deny all repo access. Global workspace containment still applies.
- **Admin Gating:** Deployment-level endpoints (`/v1/cache/clear`, `/v1/github-app/*`, `/metrics`) reject org keys with 403 — only the global admin token (or open local mode) may call them.
- **GitHub App PR Automation Caps:** Tarball downloads are size-capped (50 MB compressed, cumulative extracted size, member count) and extracted with `tarfile` data filters; diffs are pinned to immutable event SHAs via the compare endpoint.
- **Security Audit Trail (`pmcursor.audit` logger):** Every security decision emits a structured `event=<name> key=value` line — auth failures, admin denials, workspace containment rejections, rate-limit 429s, invalid webhook signatures, and org key lifecycle events. Credential material is never logged (enforced by test).
- **Non-Root Container (`Dockerfile`):** The container image runs as an unprivileged non-root user.
