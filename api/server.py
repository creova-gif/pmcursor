from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import ValidationError

from api import (
    DriftAuditRequest,
    GitHubWebhookPayload,
    audit_prd_against_repo,
    handle_github_webhook,
    verify_github_signature,
)
from pmcursor.models import DriftReport, PRImpactReport

if TYPE_CHECKING:
    from fastapi import Request as FastAPIRequest

    WebhookRequest = FastAPIRequest[Any]
else:
    from fastapi import Request as WebhookRequest


def _is_authorized(
    expected_token: str,
    authorization: str,
    x_pmcursor_token: str,
) -> bool:
    bearer_token = authorization[7:] if authorization.startswith("Bearer ") else ""
    return (
        bool(bearer_token) and hmac.compare_digest(bearer_token, expected_token)
    ) or (
        bool(x_pmcursor_token)
        and hmac.compare_digest(x_pmcursor_token, expected_token)
    )


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
            data = json.loads(payload_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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
            GitHubWebhookPayload.model_validate(data)
            return handle_github_webhook(
                payload_body,
                x_hub_signature_256,
                secret,
                allowed_workspace_root=allowed_workspace_root,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    return fastapi_app


app = create_app()
