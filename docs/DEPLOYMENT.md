# Deployment Guide

This guide covers building, configuring, and running the `pmcursor` FastAPI server in a production container environment.

## 1. Building and Running the Docker Container

The repository root includes a multi-stage [`Dockerfile`](../Dockerfile) based on `python:3.12-slim` that installs `pmcursor[server]` and runs `uvicorn api.server:app` as the non-root `pmcursor` user on port `8000`.

### Build the Image

```bash
docker build -t pmcursor:latest .
```

### Run the Container

Set `PMCURSOR_API_TOKEN` for authenticated API requests and `WEB_CONCURRENCY` to control worker count:

```bash
docker run -d \
  --name pmcursor \
  -p 8000:8000 \
  -e PMCURSOR_API_TOKEN="your-strong-api-token" \
  -e WEB_CONCURRENCY=2 \
  pmcursor:latest
```

| Environment Variable | Description | Default |
| --- | --- | --- |
| `PMCURSOR_API_TOKEN` | Bearer / `X-PMCursor-Token` secret required by authenticated `/v1/*` endpoints. | Unset |
| `PMCURSOR_RATE_LIMIT_PER_MIN` | Per-client request rate limit per minute. Exceeding the limit returns HTTP `429 Too Many Requests` with a `Retry-After` header (`/health` and `/readyz` probes are exempt). | Unset |
| `PMCURSOR_TRUST_PROXY` | Opt-in flag to resolve client IP addresses from `X-Forwarded-For` for rate limiting behind trusted reverse proxies. | Unset |
| `PMCURSOR_CORS_ORIGINS` | Comma-separated list of allowed CORS origins for the FastAPI server (CORS disabled when unset). | Unset |
| `WEB_CONCURRENCY` | Positive integer number of `uvicorn` worker processes. | `1` |
| `PYTHONPATH` | Configured in the image as `/app/src:/app`. | `/app/src:/app` |

> **Note:** When running via `pmcursor.cli` / `api.server:run_server`, `WEB_CONCURRENCY` must be a positive integer (`>= 1`). When running `uvicorn` directly via the container entrypoint, `uvicorn` also reads `WEB_CONCURRENCY`.

---

## 2. Health and Readiness Probes

The server exposes two unauthenticated probe endpoints for container orchestrators (Kubernetes, ECS, Nomad, Docker `HEALTHCHECK`):

- **Liveness (`GET /health`)**
  - Returns HTTP `200` with `{"status": "ok"}`.
  - Used by the image's built-in `HEALTHCHECK` (`http://127.0.0.1:8000/health`).
- **Readiness (`GET /readyz`)**
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

## 3. Webhook Secrets & Security Best Practices

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
- Run as the non-root `pmcursor` user (configured in `Dockerfile`).
- Terminate TLS at your ingress or load balancer; do not expose plaintext HTTP to the public internet.
- Mount only the workspace directories you intend to audit, and avoid storing secrets in repository files.
