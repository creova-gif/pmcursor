# HTTP API service

## Sub-features

- `GET /health` → `{"status":"ok"}`, `GET /readyz` → `{"status":"ready","cached_repos":N}`,
  `GET /metrics` → Prometheus text including `pmcursor_rate_limited_total` and
  `pmcursor_webhook_duplicates_total`.
- `POST /v1/drift/audit`, `/v1/tickets/audit`, `/v1/checklist`, `/v1/canvas`,
  `/v1/release-notes`, `/v1/flags/audit`, `/v1/telemetry/verify`,
  `/v1/cache/clear`, `/v1/publish`; `GET /v1/dashboard`.
- `POST /v1/webhooks/{github,linear,jira}` — HMAC-SHA256 signature-verified.
- Middleware: `X-Request-ID` / `X-Process-Time-Ms` headers on every response,
  per-IP rate limiting (`PMCURSOR_RATE_LIMIT_PER_MIN`, default 120),
  request-body cap of 2MB, optional CORS (`PMCURSOR_CORS_ORIGINS`).

## How to get to it (user POV)

A PM or an integrator starts `pmcursor serve --host 127.0.0.1 --port 8000` and
the GitHub Action / IDE calls REST endpoints. Webhooks from GitHub, Linear,
and Jira arrive at `/v1/webhooks/*` to trigger audits automatically.

## Driving it with curl/HTTP

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.cursor/skills/verify-pmcursor/helpers/up.sh 8123   # READY pid=<n> port=8123

curl -sf http://127.0.0.1:8123/health           # {"status":"ok"}
curl -sf http://127.0.0.1:8123/readyz           # {"status":"ready","cached_repos":0}
curl -s -D- -o /dev/null http://127.0.0.1:8123/health | grep -i 'x-request-id\|x-process-time'
```

Proof of working: all three probes answer, response headers include
`X-Request-ID` (a uuid) and `X-Process-Time-Ms`. Drive a real audit
(`POST /v1/drift/audit`, recipe in [drift.md](drift.md)) then re-check
`/readyz` — `cached_repos` becomes `1`, proving the index cache engaged.

Teardown: `.cursor/skills/verify-pmcursor/helpers/down.sh`.

## Gotchas

- Auth is only enforced when `PMCURSOR_API_TOKEN` (or the app factory's
  `api_token`) is set — the dev default is *open on loopback*. Proving "the API
  requires auth" without setting the token will fail; that is correct behavior.
  To verify the guard: `PMCURSOR_API_TOKEN=test-token` at launch, expect `401`
  bare, `200` with `X-PMCursor-Token` or `Authorization: Bearer`.
- `run_server` refuses non-loopback binds without `PMCURSOR_API_TOKEN`
  (`api/server.py` ~line 864) — `--host 0.0.0.0` exits immediately with the
  refusal message. That message on stderr is the observable proof of the guard.
- Rate limiting is per-client-IP; hammering `/v1/*` past the limit returns 429
  and increments `pmcursor_rate_limit_total`-style counters visible on
  `/metrics`. If a proof needs >120 requests/minute, set
  `PMCURSOR_RATE_LIMIT_PER_MIN` higher at launch — do not label your own
  hammering a bug.
- Webhook endpoints reject unsigned or wrongly-signed bodies (401/400); without
  the matching secret you can only prove the rejection path. That rejection IS
  evidence for the signature guard.
- `POST /v1/publish` really calls GitHub/Linear/Jira when configured — do not
  drive it against live services from a verification run.
- `repo_root` in request bodies resolves against the server's cwd and must sit
  under `allowed_workspace_root` when configured; `up.sh` runs from the repo
  root, so `"."` and absolute in-repo paths both work.
