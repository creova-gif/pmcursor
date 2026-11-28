# Deployment Guide

This guide covers building, configuring, and running the `pmcursor` FastAPI server in a production container environment.

## 1. Building and Running the Docker Container

The repository root includes a multi-stage [`Dockerfile`](../Dockerfile) based on `python:3.12-slim` that installs `pmcursor[server]` and runs `uvicorn api.server:app` as the non-root `pmcursor` user on port `8000`.

### Quickstart with Docker Compose

Copy [`.env.example`](../.env.example) to `.env`, set your secrets (such as `PMCURSOR_API_TOKEN`), and start the service with Docker Compose:

```bash
cp .env.example .env
docker compose up --build
```

### Build the Image

```bash
docker build -t pmcursor:latest .
```

### Run the Container

Set `PMCURSOR_API_TOKEN` for authenticated API requests:

```bash
docker run -d \
  --name pmcursor \
  -p 8000:8000 \
  -e PMCURSOR_API_TOKEN="your-strong-api-token" \
  pmcursor:latest
```

> **Worker count and per-process state:** the rate limiter, index cache, and webhook deduplicator are **per-process** — more workers proportionally weaken limits and dedup. With the default file org backend, `WEB_CONCURRENCY` must stay `1` (`run_server` refuses otherwise): worker processes would clobber the JSON store. Set `PMCURSOR_ORG_BACKEND=sqlite` for a multi-writer-safe org store — but note rate limits still apply per worker.

| Environment Variable | Description | Default |
| --- | --- | --- |
| `PMCURSOR_API_TOKEN` | Bearer / `X-PMCursor-Token` secret required by authenticated `/v1/*` endpoints. | Unset |
| `PMCURSOR_RATE_LIMIT_PER_MIN` | Per-client request rate limit per minute. Exceeding the limit returns HTTP `429 Too Many Requests` with a `Retry-After` header (`/health` and `/readyz` probes are exempt). | Unset |
| `PMCURSOR_TRUST_PROXY` | Opt-in flag to resolve client IP addresses from `X-Forwarded-For` for rate limiting behind trusted reverse proxies. | Unset |
| `PMCURSOR_CORS_ORIGINS` | Comma-separated list of allowed CORS origins for the FastAPI server (CORS disabled when unset). | Unset |
| `GITHUB_TOKEN` | GitHub personal access token or installation token used by `POST /v1/publish` and `pmcursor publish` to post PR comments. | Unset |
| `LINEAR_API_KEY` | Linear API key used by `POST /v1/publish` and `pmcursor publish` to post issue comments. | Unset |
| `JIRA_API_TOKEN` | Jira API token used by `POST /v1/publish` and `pmcursor publish` to post issue comments. | Unset |
| `WEB_CONCURRENCY` | Positive integer number of `uvicorn` worker processes — must stay `1` with the file org backend; `sqlite` permits more (rate limits remain per-worker). | `1` |
| `PMCURSOR_ORG_STORE` | Path to the org registry store enabling `pmk_` org-key auth, per-tenant rate buckets, org cache scopes, and per-org `workspace_roots`. Point it at a writable volume — the workspace mounts read-only. | Unset (org keys disabled) |
| `PMCURSOR_ORG_BACKEND` | Org registry backend: `file` (single-writer JSON) or `sqlite` (WAL, multi-worker/multi-process safe). | `file` |
| `PMCURSOR_GITHUB_APP_ID` | GitHub App id enabling installation tokens + PR automation. | Unset |
| `PMCURSOR_GITHUB_APP_PRIVATE_KEY` / `_PATH` | App private key (inline PEM or path) for JWT signing. | Unset |
| `PMCURSOR_GITHUB_APP_AUTO_RUN` | `0` disables webhook-driven PR drift automation. | `1` |
| `PMCURSOR_GITHUB_APP_PR_COMMENTS` | `0` disables failure-comment upserts on PRs. | `1` |
| `PMCURSOR_GITHUB_API_BASE` | GitHub API base for Enterprise Server. | `https://api.github.com` |
| `PYTHONPATH` | Configured in the image as `/app/src:/app`. | `/app/src:/app` |

> **Note:** When running via `pmcursor.cli` / `api.server:run_server`, `WEB_CONCURRENCY` must be a positive integer (`>= 1`). When running `uvicorn` directly via the container entrypoint, `uvicorn` also reads `WEB_CONCURRENCY`.

---

## 2. Health and Readiness Probes

The server exposes two unauthenticated probe endpoints for container orchestrators (Kubernetes, ECS, Nomad, Docker `HEALTHCHECK`):

- **Liveness (`GET /health`)**
  - Returns HTTP `200` with `{"status": "ok"}`.
  - Used by the image's built-in `HEALTHCHECK` (`http://127.0.0.1:8000/health`).
- **Readiness (`GET /readyz`)**
  - When `PMCURSOR_ORG_STORE` is configured, readiness also probes the store file and returns `503 {"detail": "org_store_unreadable"}` while it is unreadable or schema-invalid — a node with a broken registry reports not-ready instead of silently failing org-key requests.**
  - Returns HTTP `200` with `{"status": "ready", "cached_repos": <int>}`.
  - Indicates the application is ready to serve traffic and reports the number of cached repository indexes.
- **Cache Clear (`POST /v1/cache/clear`)**
  - Authenticated endpoint (requires `PMCURSOR_API_TOKEN` when configured) that clears the in-memory `RepoIndexCache` so subsequent requests re-index repositories from disk.

Example Kubernetes probe configuration:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
  timeoutSeconds: 5
readinessProbe:
  httpGet:
    path: /readyz
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 5
```

---

## 3. Team Tenancy (org keys)

Set `PMCURSOR_ORG_STORE` to a writable path (in compose, `/orgs/orgs.json` on the `pmcursor-orgs` volume) to enable per-organization API keys:

```bash
python3 -m pmcursor.cli orgs create --name Acme          # prints pmk_... once
python3 -m pmcursor.cli orgs add-root --org-id acme --root /workspace/acme-repo
```

- Org keys authenticate as `Authorization: Bearer pmk_...` alongside the admin token and get per-org rate-limit buckets and index-cache scopes.
- An org key can only reach repos under its registered `workspace_roots` (`orgs add-root`/`remove-root`); an org with no roots gets `403` on repo-touching endpoints. Admin tokens and open local mode are unaffected.
- Org keys get `403` on admin endpoints: `POST /v1/cache/clear`, `/v1/github-app/*`, and `GET /metrics` (Prometheus scrapers must carry the admin token).
- `GET /v1/whoami` reports which credential resolved (`admin` / `org-key` + `org_id` / `open`).
- Security decisions emit structured `event=` lines on the `pmcursor.audit` logger — route it to your log pipeline for auth-failure/denial alerting. Credential material is never logged.

---

## 4. Webhook Secrets & Security Best Practices

### Required Webhook Secrets

Configure provider-specific HMAC secrets as environment variables (via your secret manager, never baked into images or `.env` files in git):

| Provider | Endpoint | Environment Variable | Signature Header |
| --- | --- | --- | --- |
| GitHub | `POST /v1/webhooks/github` | `PMCURSOR_WEBHOOK_SECRET` | `X-Hub-Signature-256` |
| Linear | `POST /v1/webhooks/linear` | `PMCURSOR_LINEAR_WEBHOOK_SECRET` | `Linear-Signature` |
| Jira | `POST /v1/webhooks/jira` | `PMCURSOR_JIRA_WEBHOOK_SECRET` | `X-Hub-Signature` |

- For **GitHub** and **Linear**, requests fail with HTTP `401` if the signature header does not match the configured secret.
- For **Jira**, if `PMCURSOR_JIRA_WEBHOOK_SECRET` is set, requests are verified against `X-Hub-Signature`. If unset, the endpoint falls back to requiring `PMCURSOR_API_TOKEN` via `Authorization: Bearer <token>` or `X-PMCursor-Token`.

### Non-Loopback Bind Requirement

`api.server.run_server()` refuses to bind to any non-loopback host (anything other than `127.0.0.1`, `localhost`, or `::1`, such as `0.0.0.0`) unless `PMCURSOR_API_TOKEN` is set to a non-empty value. Always provision a strong `PMCURSOR_API_TOKEN` in containerized and network-exposed deployments.

### 2MB Webhook Payload Cap

All webhook endpoints (`/v1/webhooks/github`, `/v1/webhooks/linear`, `/v1/webhooks/jira`) enforce a strict **2MB** (`2 * 1024 * 1024` = `2,097,152` bytes) payload cap via `_read_bounded_webhook_body`:

- Checked against both the `Content-Length` header and the actual streamed request body.
- Oversized requests are rejected with HTTP `413` (`Webhook payload exceeds 2MB limit`).
- If deploying behind a reverse proxy or ingress controller (NGINX, Envoy, ALB), configure an upstream body-size limit of `2m` as defense-in-depth.

### Additional Hardening

- Configure `PMCURSOR_RATE_LIMIT_PER_MIN` to enforce per-client rate limiting (returning `429 Too Many Requests` with `Retry-After`; `/health` and `/readyz` probes are exempt).
- Enable `PMCURSOR_TRUST_PROXY` only when running behind a trusted reverse proxy or load balancer so rate limiting resolves client IPs from `X-Forwarded-For` instead of the proxy socket address. Leave it unset when directly exposed to prevent `X-Forwarded-For` spoofing.
- `GET /metrics` requires the admin token when auth is configured — point your Prometheus `bearer_token`/`authorization` at `PMCURSOR_API_TOKEN`.
- Run as the non-root `pmcursor` user (configured in `Dockerfile`).
- Terminate TLS at your ingress or load balancer; do not expose plaintext HTTP to the public internet.
- Mount only the workspace directories you intend to audit, and avoid storing secrets in repository files.

---

## 5. GitHub Code Scanning (SARIF)

You can export drift audit findings in SARIF 2.1.0 format using `pmcursor drift --sarif` and upload the resulting file to GitHub Code Scanning:

```bash
PYTHONPATH=src python3 -m pmcursor.cli drift --prd PROJECT_SPEC.md --repo . --sarif > pmcursor-drift.sarif
```

In a GitHub Actions workflow, upload `pmcursor-drift.sarif` with `github/codeql-action/upload-sarif` (requires `security-events: write` permission):

```yaml
- name: Run PMCursor drift audit (SARIF)
  run: PYTHONPATH=src python3 -m pmcursor.cli drift --prd PROJECT_SPEC.md --repo . --sarif > pmcursor-drift.sarif

- name: Upload SARIF to GitHub Code Scanning
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: pmcursor-drift.sarif
```
