from __future__ import annotations

import hmac
import importlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from api import (
    CanvasRequest,
    ChecklistRequest,
    DriftAuditRequest,
    GitHubWebhookPayload,
    ReleaseNotesRequest,
    TicketAuditRequest,
    audit_prd_against_repo,
    compute_pr_impact,
    parse_jira_webhook_issue,
    parse_linear_webhook_issue,
    verify_github_signature,
    verify_jira_signature,
    verify_linear_signature,
)
from pmcursor.checklists import EdgeCaseChecklist, generate_edge_case_checklist
from pmcursor.drift import check_spec_drift
from pmcursor.indexer import index_repository
from pmcursor.models import DriftReport, PRImpactReport
from pmcursor.release_notes import (
    ReleaseNotesReport,
    generate_release_notes_and_coverage,
)
from pmcursor.tickets import TicketSyncReport, audit_ticket_against_repo
from web.canvas import render_split_pane_canvas

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


def _require_auth(
    api_token: str | None,
    authorization: str,
    x_pmcursor_token: str,
) -> None:
    resolved_token = (
        api_token
        if api_token is not None
        else os.environ.get("PMCURSOR_API_TOKEN", "")
    )
    if resolved_token and not _is_authorized(
        resolved_token, authorization, x_pmcursor_token
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _resolve_allowed_repo_root(
    repo_root: str,
    allowed_workspace_root: Path | None,
) -> Path:
    repo_path = Path(repo_root).resolve()
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
    return repo_path


def _parse_webhook_dict_and_repo(
    payload_body: bytes,
    content_type: str,
    allowed_workspace_root: Path | None,
) -> tuple[dict[str, Any], Path]:
    try:
        data = _decode_webhook_json(payload_body, content_type)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Webhook payload must be a JSON object")
    raw_repo_root = data.get("repo_root", ".")
    repo_root = raw_repo_root if isinstance(raw_repo_root, str) else "."
    root = _resolve_allowed_repo_root(repo_root, allowed_workspace_root)
    return data, root


def create_app(
    *,
    webhook_secret: str | None = None,
    linear_webhook_secret: str | None = None,
    jira_webhook_secret: str | None = None,
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
        _require_auth(api_token, authorization, x_pmcursor_token)
        _resolve_allowed_repo_root(body.repo_root, allowed_workspace_root)
        return audit_prd_against_repo(body)

    @fastapi_app.post("/v1/tickets/audit", response_model=TicketSyncReport)
    def tickets_audit(
        body: TicketAuditRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> TicketSyncReport:
        _require_auth(api_token, authorization, x_pmcursor_token)
        repo_path = _resolve_allowed_repo_root(body.repo_root, allowed_workspace_root)
        repo_map = index_repository(repo_path)
        return audit_ticket_against_repo(
            body.ticket_id,
            body.title,
            body.description,
            repo_map,
            provider=body.provider,
            repo_root=repo_path,
        )

    @fastapi_app.post("/v1/checklist", response_model=EdgeCaseChecklist)
    def checklist_endpoint(
        body: ChecklistRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> EdgeCaseChecklist:
        _require_auth(api_token, authorization, x_pmcursor_token)
        repo_path = _resolve_allowed_repo_root(body.repo_root, allowed_workspace_root)
        repo_map = index_repository(repo_path)
        return generate_edge_case_checklist(
            repo_map,
            prd_markdown=body.prd_markdown,
            repo_root=repo_path,
        )

    @fastapi_app.post("/v1/canvas", response_class=HTMLResponse)
    def canvas_endpoint(
        body: CanvasRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> HTMLResponse:
        _require_auth(api_token, authorization, x_pmcursor_token)
        repo_path = _resolve_allowed_repo_root(body.repo_root, allowed_workspace_root)
        repo_map = index_repository(repo_path)
        report = check_spec_drift(
            body.prd_markdown,
            repo_map,
            prd_path=body.prd_path,
            repo_root=repo_path,
        )
        html_doc = render_split_pane_canvas(body.prd_markdown, repo_map, report)
        return HTMLResponse(content=html_doc)

    @fastapi_app.post("/v1/release-notes", response_model=ReleaseNotesReport)
    def release_notes_endpoint(
        body: ReleaseNotesRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> ReleaseNotesReport:
        _require_auth(api_token, authorization, x_pmcursor_token)
        repo_path = _resolve_allowed_repo_root(body.repo_root, allowed_workspace_root)
        repo_map = index_repository(repo_path)
        return generate_release_notes_and_coverage(
            body.prd_markdown,
            body.diff_text,
            repo_map,
            prd_path=body.prd_path,
            version=body.version,
            repo_root=repo_path,
        )

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

    @fastapi_app.post("/v1/webhooks/linear", response_model=None)
    async def linear_webhook(
        request: WebhookRequest,
        linear_signature: str = Header(default="", alias="Linear-Signature"),
    ) -> TicketSyncReport | dict[str, Any]:
        payload_body = await request.body()
        secret = (
            linear_webhook_secret
            if linear_webhook_secret is not None
            else os.environ.get("PMCURSOR_LINEAR_WEBHOOK_SECRET", "")
        )
        if not verify_linear_signature(payload_body, linear_signature, secret):
            raise HTTPException(
                status_code=401, detail="Invalid Linear webhook signature"
            )
        data, root = _parse_webhook_dict_and_repo(
            payload_body,
            request.headers.get("content-type", ""),
            allowed_workspace_root,
        )
        parsed = parse_linear_webhook_issue(data)
        if parsed is None:
            return {"status": "ignored", "event_type": data.get("type")}
        ticket_id, title, description = parsed
        repo_map = index_repository(root)
        return audit_ticket_against_repo(
            ticket_id,
            title,
            description,
            repo_map,
            provider="linear",
            repo_root=root,
        )

    @fastapi_app.post("/v1/webhooks/jira", response_model=None)
    async def jira_webhook(
        request: WebhookRequest,
        x_hub_signature: str = Header(default="", alias="X-Hub-Signature"),
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> TicketSyncReport | dict[str, Any]:
        payload_body = await request.body()
        jira_secret = (
            jira_webhook_secret
            if jira_webhook_secret is not None
            else os.environ.get("PMCURSOR_JIRA_WEBHOOK_SECRET", "")
        )
        if jira_secret:
            if not verify_jira_signature(payload_body, x_hub_signature, jira_secret):
                raise HTTPException(
                    status_code=401, detail="Invalid Jira webhook signature"
                )
        else:
            _require_auth(api_token, authorization, x_pmcursor_token)
        data, root = _parse_webhook_dict_and_repo(
            payload_body,
            request.headers.get("content-type", ""),
            allowed_workspace_root,
        )
        parsed = parse_jira_webhook_issue(data)
        if parsed is None:
            return {"status": "ignored", "webhook_event": data.get("webhookEvent")}
        ticket_id, title, description = parsed
        repo_map = index_repository(root)
        return audit_ticket_against_repo(
            ticket_id,
            title,
            description,
            repo_map,
            provider="jira",
            repo_root=root,
        )

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
