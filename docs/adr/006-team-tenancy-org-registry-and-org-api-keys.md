# ADR-006: Team tenancy — org registry and per-org API keys

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
M1–M22 shipped the full single-tenant product: CLI, FastAPI service, GitHub App automation, telemetry connectors, and the Next.js UI. The spec's stated model is "Open-Source CLI/GitHub App + Team SaaS", but auth today is a single global `PMCURSOR_API_TOKEN` shared by every caller, and `org_id` is only a cosmetic label on the `PRImpactReport`. There is no way to issue per-team credentials, revoke a team's access, or know which tenant a request belongs to — the minimum foundation any paid multi-tenant offering needs.

## Decision
Add `src/pmcursor/tenancy.py` — an `OrgRegistry` persisted to a JSON store file:

- `create_org(name, org_id?)` registers an org and returns its first plaintext API key; `issue_key` mints additional keys; `revoke_key` revokes by key id; `list_orgs`/`get_org` read state.
- Keys are `pmk_<key_id>_<secret>` — the key id is lookup metadata; the secret is shown once and stored only as a SHA-256 hash. Resolution (`resolve_key`) hashes the presented secret and `hmac.compare_digest`s it against the stored hash; revoked keys never resolve. On success `last_used_at` is stamped — the metering hook for future per-tenant usage tracking.
- Writes are atomic (tempfile + `os.replace`); the store is opt-in via `PMCURSOR_ORG_STORE` (CLI default `.pmcursor/orgs.json`).

`api/server.py` `_require_auth` now returns `str | None`: when an `OrgRegistry` is configured (`create_app(org_registry=...)` or `PMCURSOR_ORG_STORE`), org keys authenticate as bearer/`X-PMCursor-Token` credentials alongside the global admin token, and the resolved `org_id` is returned to the endpoint. `GET /v1/whoami` exposes the resolved identity (`admin` / `org-key` + org / `open`) so deployments and the UI can prove which tenant a credential binds.

`pmcursor orgs create|list|issue-key|revoke-key` is the management surface (`--store` or `PMCURSOR_ORG_STORE`).

## Alternatives considered
1. **Billing-first SaaS (Stripe, plans, seats)** — rejected: there are no users or requirements for billing; the tenant/auth foundation is what every later SaaS decision depends on and is pure engineering.
2. **Database-backed tenancy (Postgres/SQLite ORM)** — rejected: the product is deliberately stateless/file-backed today; a JSON store matches deployment reality (single process, filesystem) and can be swapped for a real datastore when scale demands it — `OrgRegistry` is the seam.
3. **Full request-level tenant isolation (per-org caches, repo-root allowlists, data separation)** — deferred: the API is stateless and `allowed_workspace_root` already confines filesystem access; binding `org_id` to requests and issuing scoped credentials is the meaningful increment. Per-org cache namespacing is a follow-up.
4. **JWT-issued org tokens** — rejected: opaque hashed keys are simpler, revocable without key rotation, and match GitHub's own PAT model.

## Consequences and failure modes
- The JSON store is single-writer; concurrent `orgs` CLI invocations against one store can interleave — acceptable for a management-plane tool, documented.
- `resolve_key` writes `last_used_at` on every authenticated request — one store write per request under load; if that becomes hot, batch the stamp or move it out of the auth path.
- Org-key auth is authentication + labeling only; a valid org key can still hit any `/v1/*` endpoint. Endpoint-level per-tenant scoping is a follow-up milestone.
- `pmk_` keys are bearer credentials — they grant API access to whoever holds them, same as the global token; they are shown once at issue time and never logged.
