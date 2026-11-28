# ADR-007: Per-tenant isolation — admin gating, scoped rate limits, scoped caches

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
ADR-006 made org API keys first-class credentials, but every authenticated caller still shared one authority: an org key could hit deployment-level endpoints (`POST /v1/cache/clear` wipes the global cache; the GitHub App endpoints mint installation tokens — deployment credentials), all clients shared one IP-keyed rate limiter (one noisy tenant could starve the rest), and the `RepoIndexCache` was keyed by repo path alone (tenants shared cached indexes, including each other's eviction footprint).

## Decision
Three isolation primitives, all keyed on the `org_id` M23 binds at auth time:

1. **Admin-gated endpoints** — `_require_admin` wraps `_require_auth` and returns 403 when the credential resolves to an org. Applied to `POST /v1/cache/clear` and all `/v1/github-app/*` routes — deployment management is not a tenant capability.
2. **Org-scoped rate limiting** — the request middleware resolves the presented token with `resolve_key(record_use=False)` (a peek that skips the `last_used_at` write) and buckets `org:<org_id>` when it resolves, falling back to `ip:<ip>`. Per-tenant quotas apply per org instead of per IP.
3. **Org-scoped index cache** — `RepoIndexCache` entries are keyed `(scope, path)`; `get_or_index(repo_root, scope=org_id)` namespaces tenants so one org's cached `RepoMap` is never shared with another's, and `clear(scope)` can evict a single tenant. Webhook-driven indexing (HMAC-authed, not org-keyed) stays in the default `""` scope. The admin `POST /v1/cache/clear` still clears everything (`scope=None`).

## Alternatives considered
1. **Separate rate limiter instances per org** — rejected: the existing `_SlidingWindowRateLimiter` already keys buckets by string; `org:`/`ip:` prefixes compose cleanly without new state.
2. **Sharing the cache across orgs (path-only keys)** — rejected: a shared map is functionally correct (deterministic output) but leaks across-tenant cache state — hits, eviction order, and post-`clear` behavior — and breaks the mental model of per-tenant resources the billing layer will meter.
3. **401 instead of 403 for org keys on admin endpoints** — rejected: the credential is valid and authenticated; 403 is the correct semantic (authenticated but not authorized for this resource).
4. **Per-org `allowed_workspace_root`** — deferred: today's single workspace root is a deployment property; per-tenant filesystem scoping becomes real when orgs can register their own repo roots — a billing/accounts-layer concern.

## Consequences and failure modes
- `GET /v1/whoami` is rate-limited under the org bucket — an org hitting its limit sees 429 even on the identity probe (probes `/health`/`/readyz` remain exempt).
- Two resolves happen per request when an org key is presented (middleware peek + auth stamp) — the peek is read-only so only one store write occurs per authenticated request.
- Scoped cache entries consume the same LRU budget — a busy tenant can evict another's entries globally. A per-org capacity reservation is a possible follow-up; 64 entries is ample at current scale.
- Unauthenticated requests (open mode) keep IP bucketing and the `""` cache scope — local development is unchanged.
