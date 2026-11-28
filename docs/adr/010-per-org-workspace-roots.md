# ADR-010: Per-org workspace roots — least-privilege repo access for org keys

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
ADR-007 deferred "per-tenant workspace scoping" as an accounts-layer concern, leaving a real isolation hole: any authenticated org key could reach *any* repository under the deployment's `allowed_workspace_root` — org A could index org B's repos when co-located on the same workspace. M23/M24 scoped *identity*, *rate limits*, and *caches* to the org, but repo access was still deployment-global for all callers.

## Decision
`Org.workspace_roots` is a list of absolute repo-root paths the org may reach, administered out-of-band by the deployment admin (`pmcursor orgs add-root|remove-root`, persisted in the org store, audit-logged as `org_roots_updated`).

`_resolve_allowed_repo_root` now takes the bound `org_id` + registry: for org-key-authenticated requests the resolved repo path must be relative to **both** an org-registered root (deny → 403 `repo_root_denied` audit event) **and** the deployment's global `allowed_workspace_root` when configured (org roots can only narrow, never widen, the deployment sandbox).

**Empty roots = no repo access.** An org key with no registered roots authenticates (`/v1/whoami` works) but gets 403 on every repo-touching endpoint. This is a deliberate least-privilege default — orgs are provisioned by an admin who must explicitly grant repo access; there is no silent open state.

Admin token, open local mode, and HMAC-authed webhook paths are unchanged — org scoping only engages when a `pmk_` key resolved.

Applied to every repo-touching endpoint: `/v1/index`, `/v1/drift/audit`, `/v1/summarize`, `/v1/tickets/audit`, `/v1/checklists/generate`, `/v1/fix-prd`, `/v1/pr-impact`, `/v1/flags/audit`, `/v1/telemetry/verify`, `/v1/dashboard`.

## Alternatives considered
1. **Empty roots = inherit global workspace** — rejected: silently grants every new org deployment-wide repo access; the least-privilege default forces explicit grants and is the honest pre-1.0 tightening.
2. **Per-key roots instead of per-org** — rejected: finer granularity with no current consumer; org-level is the right tenancy unit and keeps revocation simple.
3. **Roots as request-time claims** — rejected: caller-supplied claims can't be trusted; root grants must live in the admin-controlled registry.

## Consequences and failure modes
- **Back-compat tightening:** org keys created before this change have `workspace_roots: []` and lose repo access until an admin registers roots — deliberate; documented in CHANGELOG.
- `pmcursor orgs list` now shows each org's root count; `add-root` stores paths resolved (no symlink/relative ambiguity at check time).
- A root registered then removed restores denial immediately (registry writes are atomic; in-memory state shared).
- Org roots do not need to exist on disk at registration — resolution happens per request; a removed/moved root simply denies.
