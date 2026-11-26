from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import ValidationError

from api import DriftAuditRequest, audit_prd_against_repo, handle_github_webhook
from pmcursor.models import DriftReport, PRImpactReport

if TYPE_CHECKING:
    from fastapi import Request as FastAPIRequest

    WebhookRequest = FastAPIRequest[Any]
else:
    from fastapi import Request as WebhookRequest


def create_app(
    *,
    webhook_secret: str | None = None,
    allowed_workspace_root: Path | None = None,
) -> FastAPI:
    """Create and configure the PMCursor FastAPI application."""
    fastapi_app = FastAPI(title="PMCursor API")

    @fastapi_app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.post("/v1/drift/audit")
    def drift_audit(body: DriftAuditRequest) -> DriftReport:
        return audit_prd_against_repo(body)

    @fastapi_app.post("/v1/webhooks/github")
    async def github_webhook(
        request: WebhookRequest,
        x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
    ) -> PRImpactReport:
        payload_body = await request.body()
        secret = (
            webhook_secret
            if webhook_secret is not None
            else os.environ.get("PMCURSOR_WEBHOOK_SECRET", "")
        )
        try:
            return handle_github_webhook(
                payload_body,
                x_hub_signature_256,
                secret,
                allowed_workspace_root=allowed_workspace_root,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return fastapi_app


app = create_app()
