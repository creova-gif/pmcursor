from __future__ import annotations

import hmac
import importlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException
from pydantic import ValidationError

from api import (
    DriftAuditRequest,
    GitHubWebhookPayload,
    audit_prd_against_repo,
    compute_pr_impact,
    verify_github_signature,
)
from pmcursor.indexer import index_repository
from pmcursor.models import DriftReport, PRImpactReport

if TYPE_CHECKING:
    from fastapi import Request as FastAPIRequest

    WebhookRequest = FastAPIRequest[Any]
else:
    from fastapi import Request as WebhookRequest


def _token_matches(provided: str, expected_bytes: bytes) -> bool:
    if not provided:
        return False
    if hmac.compare_digest(provided.encode("utf-8"), expected_bytes):
        return True
    try:
        return hmac.compare_digest(provided.encode("latin-1"), expected_bytes)
    except UnicodeEncodeError:
        return False


def _is_authorized(
    expected_token: str,
    authorization: str,
    x_pmcursor_token: str,
) -> bool:
    expected_bytes = expected_token.encode("utf-8")
    parts = authorization.strip(" \t").split(None, 1)
    bearer_token = (
        parts[1].strip(" \t")
        if len(parts) == 2 and parts[0].lower() == "bearer"
        else ""
    )
    header_token = x_pmcursor_token.strip(" \t")
    return _token_matches(bearer_token, expected_bytes) or _token_matches(
        header_token, expected_bytes
    )


def _decode_webhook_json(payload_body: bytes, content_type: str) -> Any:
    text = payload_body.decode("utf-8")
    if "application/x-www-form-urlencoded" in content_type.lower():
        form = parse_qs(text, keep_blank_values=True)
        raw_payloads = form.get("payload")
        if not raw_payloads or not raw_payloads[0]:
            raise ValueError("Missing 'payload' field in form-encoded webhook")
        return json.loads(raw_payloads[0])
    return json.loads(text)


def create_app(
    *,
    webhook_secret: str | None = None,
    allowed_workspace_root: Path | None = None,
    api_token: str | None = None,
) -> FastAPI:
    """Create and configure the PMCursor FastAPI application."""
    fastapi_app = FastAPI(title="PMCursor API")

    @fastapi_app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.post("/v1/drift/audit")
    def drift_audit(
        body: DriftAuditRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> DriftReport:
        resolved_token = (
            api_token
            if api_token is not None
            else os.environ.get("PMCURSOR_API_TOKEN", "")
        )
        if resolved_token and not _is_authorized(
            resolved_token, authorization, x_pmcursor_token
        ):
            raise HTTPException(status_code=401, detail="Unauthorized")
        repo_path = Path(body.repo_root).resolve()
        if allowed_workspace_root is not None and not repo_path.is_relative_to(
            allowed_workspace_root.resolve()
        ):
            raise HTTPException(
                status_code=403, detail="Repository root outside allowed workspace"
            )
        if not repo_path.is_dir():
            raise HTTPException(
                status_code=404, detail="Repository directory not found"
            )
        return audit_prd_against_repo(body)

    @fastapi_app.post("/v1/webhooks/github")
    async def github_webhook(
        request: WebhookRequest,
        x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
    ) -> PRImpactReport | dict[str, Any]:
        payload_body = await request.body()
        secret = (
            webhook_secret
            if webhook_secret is not None
            else os.environ.get("PMCURSOR_WEBHOOK_SECRET", "")
        )
        if not verify_github_signature(payload_body, x_hub_signature_256, secret):
            raise HTTPException(
                status_code=401, detail="Invalid GitHub webhook signature"
            )
        try:
            content_type = request.headers.get("content-type", "")
            data = _decode_webhook_json(payload_body, content_type)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if isinstance(data, dict):
            if "zen" in data:
                return {"status": "pong", "hook_id": data.get("hook_id")}
            if "pull_request" in data and "prd_markdown" not in data:
                repo = data.get("repository")
                repo_name = repo.get("full_name") if isinstance(repo, dict) else None
                return {
                    "status": "accepted",
                    "action": data.get("action"),
                    "pr_number": data.get("number"),
                    "repository": repo_name,
                }
        try:
            payload = GitHubWebhookPayload.model_validate(data)
            root = Path(payload.repo_root).resolve()
            if (
                allowed_workspace_root is not None
                and not root.is_relative_to(allowed_workspace_root.resolve())
            ):
                raise PermissionError("Repository root outside allowed workspace")
            repo_map = index_repository(root)
            return compute_pr_impact(
                payload.prd_markdown,
                payload.diff_text,
                repo_map,
                prd_path=payload.prd_path,
                org_id=payload.org_id,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    return fastapi_app


app = create_app()


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the PMCursor FastAPI server using uvicorn."""
    if (
        not _is_loopback_host(host)
        and not os.environ.get("PMCURSOR_API_TOKEN", "").strip()
    ):
        raise ValueError(
            f"Refusing to bind non-loopback host '{host}' without PMCURSOR_API_TOKEN set. "
            "Set PMCURSOR_API_TOKEN or bind to 127.0.0.1."
        )
    raw_concurrency = os.environ.get("WEB_CONCURRENCY", "").strip()
    workers = 1
    if raw_concurrency:
        try:
            workers = int(raw_concurrency)
        except ValueError as exc:
            raise ValueError(
                f"Invalid WEB_CONCURRENCY value '{raw_concurrency}': must be a positive integer."
            ) from exc
        if workers <= 0:
            raise ValueError(
                f"Invalid WEB_CONCURRENCY value '{raw_concurrency}': must be a positive integer."
            )
    try:
        uvicorn_module: Any = importlib.import_module("uvicorn")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "uvicorn is required to run the server. Install with: pip install 'pmcursor[server]'"
        ) from exc
    if workers > 1:
        uvicorn_module.run("api.server:app", host=host, port=port, workers=workers)
    else:
        uvicorn_module.run(app, host=host, port=port)
