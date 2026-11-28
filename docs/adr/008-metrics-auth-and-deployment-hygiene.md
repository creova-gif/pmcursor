# ADR-008: Metrics endpoint auth and deployment hygiene

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
The Prometheus `/metrics` endpoint was unauthenticated: any caller — including per-org `pmk_` keys introduced in M23 — could read deployment-wide counters (`pmcursor_http_requests_total`, `pmcursor_rate_limited_total`, cache gauges). Those counters span tenants, so an org key holder could observe other tenants' aggregate activity — a cross-tenant information leak that M24's isolation model did not cover. Separately, operational hygiene had drifted: `.env.example` documented only the pre-M17 env surface, `docker-compose.yml` lacked the tenancy/GitHub-App/telemetry vars and any writable path for the org store (workspace mounts are read-only), Dependabot did not cover `npm` (`ui/`) or `docker`, and the Dockerfile was never built in CI.

## Decision
- **`/metrics` requires admin auth** — same `_require_admin` rule as `/v1/cache/clear` and `/v1/github-app/*`: org keys get 403, anonymous callers get 401 when auth is configured, open local mode is unaffected. Rationale: global counters are a deployment observation surface, not a tenant resource; Prometheus scrapers should carry the admin token.
- **`.env.example` covers the full env surface** — grouped by feature (auth/webhooks, tenancy, rate limiting, LLM, GitHub App, telemetry connectors, ticket sync) so operators can discover every knob in one place.
- **Compose gains the missing env passthroughs** plus a `pmcursor-orgs` named volume at `/orgs` for the org registry — the workspace bind mounts read-only, and the Dockerfile now pre-creates `/orgs` owned by `pmcursor` so fresh named volumes inherit writable ownership.
- **Dependabot covers `npm` (`/ui`) and `docker`** alongside `pip` and `github-actions`; **CI gains a `docker` job** that builds the image and smoke-imports `pmcursor` + `api.server`, so Dockerfile drift fails the gate instead of surfacing at deploy time.

## Alternatives considered
1. **Per-tenant metric labels** — rejected: org labels on global counters would expose per-tenant request volume to whoever reads the endpoint; keeping the surface admin-only preserves isolation with zero cardinality risk.
2. **Separate internal port for metrics** — rejected: adds a second listener and deployment complexity; auth on the existing path achieves the same boundary.
3. **Bind-mount a host path for the org store** — rejected: named volume survives host layout and works on fresh clones without host path management.

## Consequences and failure modes
- Prometheus scrape configs must now send the admin bearer token; open-mode local dev unchanged.
- Orgs data persists in the `pmcursor-orgs` volume across container restarts; `docker compose down -v` deletes it (documented volume semantics, not a foot-gun since dev stores live on the host).
- The docker CI job adds ~1-2 min of wall time; it runs in parallel with `test` and `ui`.
