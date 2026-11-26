# ADR-003: FastAPI webhook server and composite GitHub Action

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
Teams need automated PRD drift checks in pull request workflows and an HTTP endpoint for GitHub webhook events. The core functions `audit_prd_against_repo` and `handle_github_webhook` in `api/__init__.py` had no HTTP server wrapper or reusable CI action.

## Decision
Expose the API functions over FastAPI in `api/server.py` and package the CLI drift command as a composite GitHub Action in `.github/actions/pmcursor-drift/action.yml`:
1. `create_app` in `api/server.py` builds a FastAPI application with optional `webhook_secret` and `allowed_workspace_root` arguments and exports a default `app` instance.
2. `GET /health` returns `{"status": "ok"}`.
3. `POST /v1/drift/audit` accepts `DriftAuditRequest`, calls `audit_prd_against_repo`, and returns `DriftReport`.
4. `POST /v1/webhooks/github` reads raw request bytes and the `X-Hub-Signature-256` header, resolves the secret from `webhook_secret` or `PMCURSOR_WEBHOOK_SECRET`, and calls `handle_github_webhook`. It maps `PermissionError` to HTTP `401` and `ValidationError` to HTTP `422`.
5. `.github/actions/pmcursor-drift/action.yml` uses `actions/setup-python@v5` with `python-version` defaulting to `"3.12"`, installs the package from `${{ github.action_path }}/../../..`, and runs `pmcursor drift --prd "${{ inputs.prd }}" --repo "${{ inputs.repo }}" --md`. It appends `--fail-on-drift` when `inputs.fail-on-drift` is `"true"`.

## Alternatives considered
1. Shelling out to the `pmcursor` CLI from an external webhook receiver adds subprocess startup overhead and duplicates payload validation.
2. Shipping a Docker-based GitHub Action adds image build time to every workflow run compared to a composite action that installs the Python package directly.
3. Parsing webhook JSON before verifying `X-Hub-Signature-256` exposes Pydantic model validation to unauthenticated requests.

## Consequences and failure modes
- `POST /v1/webhooks/github` returns HTTP `401` when `PMCURSOR_WEBHOOK_SECRET` is empty or `X-Hub-Signature-256` does not match, so misconfigured webhook deployments fail closed.
- `POST /v1/drift/audit` accepts `repo_root` without HMAC authentication, so deployments exposing `api/server.py` outside localhost must restrict network access.
- The composite action assumes `pyproject.toml` sits three directories above `.github/actions/pmcursor-drift`.
