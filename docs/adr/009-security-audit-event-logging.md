# ADR-009: Security audit event logging

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
Before this change the deployment had security *controls* (auth, signature verification, rate limiting, admin gating) but no security *trail*: a brute-force against `PMCURSOR_API_TOKEN`, an org key probing admin endpoints, a flood of invalid webhook signatures, or rate-limit throttling produced only anonymous aggregate counters on `/metrics`. An enterprise deployer or SOC cannot answer "was anyone denied, when, and from which class of caller?" — a baseline audit requirement for any authenticated service.

## Decision
Emit structured audit lines on a dedicated `pmcursor.audit` logger at every security-decision point:

| Event | Site | Level |
|-------|------|-------|
| `auth_failure` | `_require_auth` 401 | warning |
| `admin_denied` | `_require_admin` 403 (org key on admin endpoint) | warning |
| `repo_root_denied` | workspace containment 403 | warning |
| `rate_limited` | middleware 429 (fields: bucket class `org`/`ip`, path) | warning |
| `webhook_signature_invalid` | GitHub/Linear/Jira signature failures | warning |
| `org_created` / `org_key_issued` / `org_key_revoked` | `OrgRegistry` lifecycle | info |

Format is `event=<name> key=value ...` — greppable without a schema and ingestible by any log pipeline. A dedicated logger name lets operators route audit lines to a SIEM independently of app logs.

**Hard rule:** credential material is never a field — no tokens, key secrets, signatures, or webhook bodies. Denial events carry only caller *class* (`presented=`, `org_id=`, bucket class), and a regression test asserts the plaintext org secret and admin token never appear in captured audit output.

## Alternatives considered
1. **JSON-structured log lines** — rejected: stdlib `logging` has no JSON formatter and no dependency is warranted; `key=value` is equally parseable for the event vocabulary here.
2. **Per-request access logging** — rejected: noisy, and access logs are the reverse-proxy's job; audit events are only *decisions*, not traffic.
3. **Persisting audit events in the org store** — rejected: the store is a credential registry, not a log; durable audit belongs in the deployment's log pipeline.

## Consequences and failure modes
- Every denial now has a traceable line; operators can alert on `event=auth_failure` rate for brute-force detection.
- `last_used_at` stamping already meters successful org-key use; failures now have parity via `auth_failure`.
- `bucket=org` deliberately logs the bucket *class*, not the org id — org id on every 429 is fine to add later if needed; class avoids leaking tenant identity into shared log pipelines.
