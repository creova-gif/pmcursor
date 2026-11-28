from __future__ import annotations

import asyncio
import hmac
import importlib
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import ValidationError

from api import (
    CanvasRequest,
    ChecklistRequest,
    DriftAuditRequest,
    FlagAuditRequest,
    GitHubManifestConversionRequest,
    GitHubWebhookPayload,
    IndexRequest,
    OrgDashboardSummary,
    PublishCommentRequest,
    ReleaseNotesRequest,
    SummarizeRequest,
    TelemetryVerifyRequest,
    TicketAuditRequest,
    compute_pr_impact,
    parse_jira_webhook_issue,
    parse_linear_webhook_issue,
    verify_github_signature,
    verify_jira_signature,
    verify_linear_signature,
)
from pmcursor.checklists import EdgeCaseChecklist, generate_edge_case_checklist
from pmcursor.drift import check_spec_drift
from pmcursor.feature_flags import (
    FlagAuditReport,
    audit_feature_flags_and_rollout,
    extract_feature_flags,
)
from pmcursor.github_app import (
    GITHUB_API_BASE,
    GitHubAppAuth,
    GitHubAppCredentials,
    GitHubAppError,
    GitHubInstallationToken,
    build_app_manifest,
    default_github_app,
    exchange_manifest_code,
)
from pmcursor.github_pr_automation import (
    DEFAULT_CHECK_RUN_NAME,
    DEFAULT_PRD_CANDIDATES,
    PR_AUTOMATION_ACTIONS,
    GitHubAutomationError,
    build_repo_client,
    run_pull_request_automation,
)
from pmcursor.llm import (
    LLMClient,
    PMDriftSummary,
    default_llm_client,
    summarize_drift_report,
)
from pmcursor.mcp_server import RepoIndexCache
from pmcursor.models import DriftReport, PRImpactReport, RepoMap
from pmcursor.publisher import (
    PublishResult,
    publish_github_pr_comment,
    publish_jira_comment,
    publish_linear_comment,
)
from pmcursor.release_notes import (
    ReleaseNotesReport,
    compute_scope_coverage,
    generate_release_notes_and_coverage,
)
from pmcursor.telemetry_connectors import (
    ConnectorFetchError,
    fetch_telemetry_events,
)
from pmcursor.telemetry_verify import (
    TelemetryVerificationReport,
    verify_telemetry_samples,
)
from pmcursor.tenancy import (
    ENV_ORG_BACKEND,
    OrgRegistryError,
    OrgStore,
    default_org_registry,
)
from pmcursor.tickets import TicketSyncReport, audit_ticket_against_repo
from web.canvas import render_split_pane_canvas

if TYPE_CHECKING:
    from fastapi import Request as FastAPIRequest

    WebhookRequest = FastAPIRequest[Any]
else:
    from fastapi import Request as WebhookRequest

MAX_REQUEST_BYTES = 2 * 1024 * 1024  # 2_097_152 bytes
MAX_WEBHOOK_BYTES = MAX_REQUEST_BYTES

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("pmcursor.audit")


def _audit(event: str, **fields: object) -> None:
    """Emit a structured security-audit line on the pmcursor.audit logger.

    Fields are rendered as key=value pairs. Credential material (tokens,
    signatures, secrets) must never be passed here.
    """
    rendered = " ".join(f"{key}={value}" for key, value in fields.items())
    audit_logger.warning("event=%s %s", event, rendered)


async def _read_bounded_webhook_body(request: WebhookRequest) -> bytes:
    raw_content_length = request.headers.get("content-length")
    if raw_content_length is not None:
        try:
            if int(raw_content_length) > MAX_WEBHOOK_BYTES:
                raise HTTPException(
                    status_code=413, detail="Webhook payload exceeds 2MB limit"
                )
        except ValueError:
            pass
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=413, detail="Webhook payload exceeds 2MB limit"
        )
    return body


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


def _presented_token(authorization: str, x_pmcursor_token: str) -> str:
    parts = authorization.strip(" \t").split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip(" \t")
    return x_pmcursor_token.strip(" \t")


def _require_auth(
    api_token: str | None,
    authorization: str,
    x_pmcursor_token: str,
    org_registry: OrgStore | None = None,
) -> str | None:
    resolved_token = (
        api_token
        if api_token is not None
        else os.environ.get("PMCURSOR_API_TOKEN", "")
    )
    if resolved_token and _is_authorized(
        resolved_token, authorization, x_pmcursor_token
    ):
        return None
    if org_registry is not None:
        org_id = org_registry.resolve_key(
            _presented_token(authorization, x_pmcursor_token)
        )
        if org_id is not None:
            return org_id
    if resolved_token or org_registry is not None:
        _audit(
            "auth_failure",
            presented=bool(_presented_token(authorization, x_pmcursor_token)),
        )
        raise HTTPException(status_code=401, detail="Unauthorized")
    return None


def _require_admin(
    api_token: str | None,
    authorization: str,
    x_pmcursor_token: str,
    org_registry: OrgStore | None = None,
) -> None:
    """Like _require_auth but rejects organization API keys.

    Deployment-level endpoints (cache management, GitHub App credential
    minting) are admin-only: an org key authenticates but gets 403 here.
    """
    org_id = _require_auth(
        api_token, authorization, x_pmcursor_token, org_registry
    )
    if org_id is not None:
        _audit("admin_denied", org_id=org_id)
        raise HTTPException(
            status_code=403,
            detail="Organization API keys cannot access this endpoint",
        )


def _resolve_allowed_repo_root(
    repo_root: str,
    allowed_workspace_root: Path | None,
    org_id: str | None = None,
    org_registry: OrgStore | None = None,
) -> Path:
    repo_path = Path(repo_root).resolve()
    if allowed_workspace_root is not None and not repo_path.is_relative_to(
        allowed_workspace_root.resolve()
    ):
        _audit("repo_root_denied", repo_root=repo_path)
        raise HTTPException(
            status_code=403, detail="Repository root outside allowed workspace"
        )
    if org_id is not None and org_registry is not None:
        org = org_registry.get_org(org_id)
        allowed_roots = [
            Path(root).resolve()
            for root in (org.workspace_roots if org is not None else [])
        ]
        if not any(repo_path.is_relative_to(root) for root in allowed_roots):
            _audit("repo_root_denied", org_id=org_id, repo_root=repo_path)
            raise HTTPException(
                status_code=403,
                detail="Repository root outside org workspace roots",
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


class _SlidingWindowRateLimiter:
    """Thread-safe bounded-LRU per-client sliding-window rate limiter."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float = 60.0,
        max_clients: int = 10_000,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be a positive integer")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_clients < 1:
            raise ValueError("max_clients must be at least 1")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_clients = max_clients
        self._lock = threading.Lock()
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, client_key: str) -> bool:
        """Return True if the request is within the rate limit, False otherwise."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        with self._lock:
            timestamps = self._buckets.get(client_key)
            if timestamps is None:
                timestamps = deque()
                self._buckets[client_key] = timestamps
                if len(self._buckets) > self._max_clients:
                    self._buckets.popitem(last=False)
            else:
                self._buckets.move_to_end(client_key)
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self._max_requests:
                return False
            timestamps.append(now)
            return True


class _DeliveryDeduplicator:
    """Thread-safe bounded FIFO/LRU webhook delivery ID deduplicator."""

    def __init__(self, max_entries: int = 1024) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be a positive integer")
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._seen: OrderedDict[str, None] = OrderedDict()

    def mark_if_new(self, delivery_id: str) -> bool:
        """Record delivery_id if unseen; return True if new, False if duplicate."""
        with self._lock:
            if delivery_id in self._seen:
                self._seen.move_to_end(delivery_id)
                return False
            self._seen[delivery_id] = None
            if len(self._seen) > self._max_entries:
                self._seen.popitem(last=False)
            return True


def _parse_github_pr_target(target: str) -> tuple[str, int]:
    """Parse an 'owner/repo#pr_number' target string for GitHub PR publishing."""
    repo_part, sep, pr_part = target.strip().partition("#")
    if not sep or "/" not in repo_part or not pr_part.isdigit():
        raise ValueError("GitHub publish target must be formatted as 'owner/repo#pr_number'")
    owner, _, repo = repo_part.partition("/")
    if not owner or not repo or "/" in repo:
        raise ValueError("GitHub publish target must be formatted as 'owner/repo#pr_number'")
    pr_number = int(pr_part)
    if pr_number <= 0:
        raise ValueError("GitHub PR number must be a positive integer")
    return f"{owner}/{repo}", pr_number


def _resolve_publish_token(primary_env: str, fallback_env: str) -> str | None:
    for env_name in (primary_env, fallback_env):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return None


def _dispatch_publish(payload: PublishCommentRequest) -> PublishResult:
    """Dispatch a comment publish request to the configured provider."""
    if payload.provider == "github":
        repo_full_name, pr_number = _parse_github_pr_target(payload.target)
        token = (
            None
            if payload.dry_run
            else _resolve_publish_token("GITHUB_TOKEN", "PMCURSOR_GITHUB_TOKEN")
        )
        return publish_github_pr_comment(
            repo_full_name,
            pr_number,
            payload.body,
            token=token,
            dry_run=payload.dry_run,
        )
    if payload.provider == "linear":
        issue_id = payload.target.strip()
        if not issue_id:
            raise ValueError("Linear issue_id target must not be empty")
        api_key = (
            None
            if payload.dry_run
            else _resolve_publish_token("LINEAR_API_KEY", "PMCURSOR_LINEAR_API_KEY")
        )
        return publish_linear_comment(
            issue_id,
            payload.body,
            api_key=api_key,
            dry_run=payload.dry_run,
        )
    issue_key = payload.target.strip()
    if not issue_key:
        raise ValueError("Jira issue_key target must not be empty")
    if not payload.jira_base_url or not payload.jira_base_url.strip():
        raise ValueError("jira_base_url is required when publishing to Jira")
    bearer_token = (
        None
        if payload.dry_run
        else _resolve_publish_token("JIRA_API_TOKEN", "PMCURSOR_JIRA_API_TOKEN")
    )
    return publish_jira_comment(
        payload.jira_base_url.strip(),
        issue_key,
        payload.body,
        bearer_token=bearer_token,
        dry_run=payload.dry_run,
    )


def _resolve_rate_limit(rate_limit_per_minute: int | None) -> int | None:
    """Resolve effective per-minute rate limit from argument or environment."""
    if rate_limit_per_minute is not None:
        if rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be a positive integer")
        return rate_limit_per_minute
    raw_env = os.environ.get("PMCURSOR_RATE_LIMIT_PER_MIN", "").strip()
    if not raw_env:
        return None
    try:
        parsed = int(raw_env)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def _extract_client_ip(request: WebhookRequest, *, trust_proxy: bool) -> str:
    """Resolve client IP from X-Forwarded-For when trust_proxy is enabled."""
    if trust_proxy:
        forwarded_for = request.headers.get("x-forwarded-for", "").strip()
        if forwarded_for:
            first_ip = forwarded_for.split(",", 1)[0].strip()
            if first_ip:
                return first_ip
    return request.client.host if request.client is not None else "unknown"


def create_app(
    *,
    webhook_secret: str | None = None,
    linear_webhook_secret: str | None = None,
    jira_webhook_secret: str | None = None,
    allowed_workspace_root: Path | None = None,
    api_token: str | None = None,
    repo_cache: RepoIndexCache | None = None,
    rate_limit_per_minute: int | None = None,
    trust_proxy: bool | None = None,
    cors_origins: list[str] | None = None,
    llm_client: LLMClient | None = None,
    github_app: GitHubAppAuth | None = None,
    github_api_base: str | None = None,
    auto_run_pull_requests: bool | None = None,
    pr_failure_comments: bool | None = None,
    org_registry: OrgStore | None = None,
) -> FastAPI:
    """Create and configure the PMCursor FastAPI application."""
    fastapi_app = FastAPI(title="PMCursor API")
    cache = repo_cache if repo_cache is not None else RepoIndexCache()
    org_registry = (
        org_registry if org_registry is not None else default_org_registry()
    )
    effective_llm_client = llm_client if llm_client is not None else default_llm_client()
    effective_github_app = (
        github_app if github_app is not None else default_github_app()
    )
    effective_github_api_base = (
        github_api_base
        or os.environ.get("PMCURSOR_GITHUB_API_BASE")
        or GITHUB_API_BASE
    )
    effective_pr_automation = (
        auto_run_pull_requests
        if auto_run_pull_requests is not None
        else os.environ.get("PMCURSOR_GITHUB_APP_AUTO_RUN", "1")
        .strip()
        .lower()
        not in {"0", "false", "no"}
    )
    effective_pr_comments = (
        pr_failure_comments
        if pr_failure_comments is not None
        else os.environ.get("PMCURSOR_GITHUB_APP_PR_COMMENTS", "1")
        .strip()
        .lower()
        not in {"0", "false", "no"}
    )
    effective_rate_limit = _resolve_rate_limit(rate_limit_per_minute)
    effective_trust_proxy = (
        trust_proxy
        if trust_proxy is not None
        else os.environ.get("PMCURSOR_TRUST_PROXY", "").strip().lower()
        in {"1", "true", "yes"}
    )
    raw_cors_origins = (
        cors_origins
        if cors_origins is not None
        else os.environ.get("PMCURSOR_CORS_ORIGINS", "").split(",")
    )
    effective_cors_origins = [
        origin.strip() for origin in raw_cors_origins if origin.strip()
    ]
    if effective_cors_origins:
        fastapi_app.add_middleware(
            CORSMiddleware,
            allow_origins=effective_cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-PMCursor-Token",
                "X-Request-ID",
            ],
        )
    rate_limiter = (
        _SlidingWindowRateLimiter(effective_rate_limit)
        if effective_rate_limit is not None
        else None
    )
    delivery_deduplicator = _DeliveryDeduplicator()
    metrics_lock = threading.Lock()
    total_requests = 0
    error_requests = 0
    rate_limited_requests = 0
    webhook_duplicate_deliveries = 0

    def _check_duplicate_delivery(
        provider: str, raw_delivery_id: str
    ) -> dict[str, str] | None:
        nonlocal webhook_duplicate_deliveries
        delivery_id = raw_delivery_id.strip()
        if delivery_id and not delivery_deduplicator.mark_if_new(
            f"{provider}:{delivery_id}"
        ):
            with metrics_lock:
                webhook_duplicate_deliveries += 1
            return {"status": "duplicate", "delivery_id": delivery_id}
        return None

    @fastapi_app.middleware("http")
    async def request_context_middleware(
        request: WebhookRequest,
        call_next: Callable[[WebhookRequest], Awaitable[Response]],
    ) -> Response:
        nonlocal total_requests, error_requests, rate_limited_requests
        incoming_id = request.headers.get("x-request-id", "").strip()
        request_id = incoming_id or str(uuid.uuid4())
        start = time.perf_counter()

        is_probe = request.method == "GET" and request.url.path in {"/health", "/readyz"}
        rate_limited = False
        if rate_limiter is not None and not is_probe:
            bucket_key: str | None = None
            if org_registry is not None:
                presented = _presented_token(
                    request.headers.get("authorization", ""),
                    request.headers.get("x-pmcursor-token", ""),
                )
                if presented:
                    resolved_org = await asyncio.to_thread(
                        org_registry.resolve_key, presented, record_use=False
                    )
                    if resolved_org is not None:
                        bucket_key = f"org:{resolved_org}"
            if bucket_key is None:
                bucket_key = "ip:" + _extract_client_ip(
                    request, trust_proxy=effective_trust_proxy
                )
            if not rate_limiter.allow(bucket_key):
                rate_limited = True
                _audit(
                    "rate_limited",
                    bucket=bucket_key.split(":", 1)[0],
                    path=request.url.path,
                )

        if rate_limited:
            response: Response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": "60"},
            )
        else:
            payload_too_large = False
            raw_content_length = request.headers.get("content-length")
            if raw_content_length is not None:
                try:
                    content_length = int(raw_content_length)
                except ValueError:
                    content_length = None
                if content_length is not None and (
                    content_length < 0 or content_length > MAX_REQUEST_BYTES
                ):
                    payload_too_large = True

            if not payload_too_large:
                body = await request.body()
                if len(body) > MAX_REQUEST_BYTES:
                    payload_too_large = True

            if payload_too_large:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "Request payload exceeds 2MB limit"},
                )
            else:
                response = await call_next(request)

        with metrics_lock:
            total_requests += 1
            if response.status_code >= 400:
                error_requests += 1
            if rate_limited:
                rate_limited_requests += 1
        duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        logger.info(
            json.dumps(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "request_id": request_id,
                }
            )
        )
        return response

    @fastapi_app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.get("/readyz")
    def readyz() -> dict[str, Any]:
        if org_registry is not None:
            try:
                org_registry.verify()
            except OrgRegistryError as exc:
                logger.warning("readyz: org store probe failed: %s", exc)
                raise HTTPException(
                    status_code=503, detail="org_store_unreadable"
                ) from exc
        return {"status": "ready", "cached_repos": cache.size}

    @fastapi_app.get("/v1/whoami")
    def whoami(
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> dict[str, Any]:
        org_id = _require_auth(
            api_token, authorization, x_pmcursor_token, org_registry
        )
        if org_id is not None:
            return {"authenticated": True, "auth": "org-key", "org_id": org_id}
        resolved_admin = (
            api_token
            if api_token is not None
            else os.environ.get("PMCURSOR_API_TOKEN", "")
        )
        if resolved_admin or org_registry is not None:
            return {"authenticated": True, "auth": "admin", "org_id": None}
        return {"authenticated": False, "auth": "open", "org_id": None}

    @fastapi_app.get("/metrics", response_class=PlainTextResponse)
    def metrics(
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> PlainTextResponse:
        _require_admin(api_token, authorization, x_pmcursor_token, org_registry)
        with metrics_lock:
            current_total_requests = total_requests
            current_error_requests = error_requests
            rate_limited_count = rate_limited_requests
            dup_count = webhook_duplicate_deliveries
        cache_hits = int(getattr(cache, "hits", 0))
        cache_misses = int(getattr(cache, "misses", 0))
        lines = [
            "# HELP pmcursor_http_requests_total Total HTTP requests processed.",
            "# TYPE pmcursor_http_requests_total counter",
            f"pmcursor_http_requests_total {current_total_requests}",
            "# HELP pmcursor_http_errors_total Total HTTP error responses (status >= 400).",
            "# TYPE pmcursor_http_errors_total counter",
            f"pmcursor_http_errors_total {current_error_requests}",
            "# HELP pmcursor_rate_limited_total Total HTTP requests rejected by rate limiting (429).",
            "# TYPE pmcursor_rate_limited_total counter",
            f"pmcursor_rate_limited_total {rate_limited_count}",
            "# HELP pmcursor_webhook_duplicates_total Total duplicate webhook deliveries skipped.",
            "# TYPE pmcursor_webhook_duplicates_total counter",
            f"pmcursor_webhook_duplicates_total {dup_count}",
            "# HELP pmcursor_repo_cache_entries Number of cached repository maps.",
            "# TYPE pmcursor_repo_cache_entries gauge",
            f"pmcursor_repo_cache_entries {cache.size}",
            "# HELP pmcursor_repo_cache_hits_total Total repository index cache hits.",
            "# TYPE pmcursor_repo_cache_hits_total counter",
            f"pmcursor_repo_cache_hits_total {cache_hits}",
            "# HELP pmcursor_repo_cache_misses_total Total repository index cache misses.",
            "# TYPE pmcursor_repo_cache_misses_total counter",
            f"pmcursor_repo_cache_misses_total {cache_misses}",
        ]
        return PlainTextResponse(
            content="\n".join(lines) + "\n",
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @fastapi_app.post("/v1/cache/clear")
    def clear_cache(
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> dict[str, Any]:
        _require_admin(api_token, authorization, x_pmcursor_token, org_registry)
        cleared = cache.size
        cache.clear()
        return {"status": "cleared", "cleared_entries": cleared}

    @fastapi_app.post("/v1/index", response_model=RepoMap)
    def index_endpoint(
        body: IndexRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> RepoMap:
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        repo_path = _resolve_allowed_repo_root(
            body.repo_root, allowed_workspace_root, org_id, org_registry
        )
        return cache.get_or_index(repo_path, scope=org_id or "")

    @fastapi_app.post("/v1/drift/audit")
    def drift_audit(
        body: DriftAuditRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> DriftReport:
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        repo_path = _resolve_allowed_repo_root(
            body.repo_root, allowed_workspace_root, org_id, org_registry
        )
        repo_map = cache.get_or_index(repo_path, scope=org_id or "")
        return check_spec_drift(
            body.prd_markdown,
            repo_map,
            prd_path=body.prd_path,
            repo_root=repo_path,
        )

    @fastapi_app.post("/v1/summarize", response_model=PMDriftSummary)
    def summarize_endpoint(
        body: SummarizeRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> PMDriftSummary:
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        repo_path = _resolve_allowed_repo_root(
            body.repo_root, allowed_workspace_root, org_id, org_registry
        )
        repo_map = cache.get_or_index(repo_path, scope=org_id or "")
        report = check_spec_drift(
            body.prd_markdown,
            repo_map,
            prd_path=body.prd_path,
            repo_root=repo_path,
        )
        client = None if body.offline else effective_llm_client
        return summarize_drift_report(report, llm_client=client)

    @fastapi_app.post("/v1/tickets/audit", response_model=TicketSyncReport)
    def tickets_audit(
        body: TicketAuditRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> TicketSyncReport:
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        repo_path = _resolve_allowed_repo_root(
            body.repo_root, allowed_workspace_root, org_id, org_registry
        )
        repo_map = cache.get_or_index(repo_path, scope=org_id or "")
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
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        repo_path = _resolve_allowed_repo_root(
            body.repo_root, allowed_workspace_root, org_id, org_registry
        )
        repo_map = cache.get_or_index(repo_path, scope=org_id or "")
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
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        repo_path = _resolve_allowed_repo_root(
            body.repo_root, allowed_workspace_root, org_id, org_registry
        )
        repo_map = cache.get_or_index(repo_path, scope=org_id or "")
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
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        repo_path = _resolve_allowed_repo_root(
            body.repo_root, allowed_workspace_root, org_id, org_registry
        )
        repo_map = cache.get_or_index(repo_path, scope=org_id or "")
        return generate_release_notes_and_coverage(
            body.prd_markdown,
            body.diff_text,
            repo_map,
            prd_path=body.prd_path,
            version=body.version,
            repo_root=repo_path,
        )

    @fastapi_app.post("/v1/flags/audit", response_model=FlagAuditReport)
    def flags_audit_endpoint(
        payload: FlagAuditRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> FlagAuditReport:
        org_id = _require_auth(
            api_token, authorization, x_pmcursor_token, org_registry
        )
        repo_path = _resolve_allowed_repo_root(
            payload.repo_root, allowed_workspace_root, org_id, org_registry
        )
        return audit_feature_flags_and_rollout(payload.prd_markdown, repo_path)

    @fastapi_app.post("/v1/telemetry/verify", response_model=TelemetryVerificationReport)
    def telemetry_verify_endpoint(
        body: TelemetryVerifyRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> TelemetryVerificationReport:
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        if (body.events is None) == (body.source is None):
            raise HTTPException(
                status_code=422,
                detail="Provide exactly one of 'events' or 'source'.",
            )
        repo_path = _resolve_allowed_repo_root(
            body.repo_root, allowed_workspace_root, org_id, org_registry
        )
        repo_map = cache.get_or_index(repo_path, scope=org_id or "")
        if body.source is not None:
            try:
                fetched = fetch_telemetry_events(body.source, limit=body.limit)
            except ConnectorFetchError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            return verify_telemetry_samples(
                repo_map, [e.model_dump() for e in fetched.events]
            )
        return verify_telemetry_samples(repo_map, body.events or [])

    @fastapi_app.get("/v1/github-app/manifest")
    def github_app_manifest_endpoint(
        name: str = "pmcursor-drift",
        webhook_url: str = "",
        redirect_url: str | None = None,
        homepage_url: str = "https://github.com/creova-gif/pmcursor",
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> dict[str, Any]:
        _require_admin(api_token, authorization, x_pmcursor_token, org_registry)
        if not webhook_url.strip():
            raise HTTPException(
                status_code=422, detail="webhook_url is required"
            )
        try:
            return build_app_manifest(
                name=name,
                webhook_url=webhook_url,
                redirect_url=redirect_url,
                homepage_url=homepage_url,
            )
        except (GitHubAppError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @fastapi_app.post(
        "/v1/github-app/manifest/conversions",
        response_model=GitHubAppCredentials,
    )
    def github_app_manifest_conversion_endpoint(
        body: GitHubManifestConversionRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> GitHubAppCredentials:
        _require_admin(api_token, authorization, x_pmcursor_token, org_registry)
        try:
            return exchange_manifest_code(body.code)
        except GitHubAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @fastapi_app.post(
        "/v1/github-app/installations/{installation_id}/token",
        response_model=GitHubInstallationToken,
    )
    def github_app_installation_token_endpoint(
        installation_id: int,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> GitHubInstallationToken:
        _require_admin(api_token, authorization, x_pmcursor_token, org_registry)
        if effective_github_app is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "GitHub App is not configured. Set PMCURSOR_GITHUB_APP_ID "
                    "and PMCURSOR_GITHUB_APP_PRIVATE_KEY."
                ),
            )
        try:
            return effective_github_app.installation_token(installation_id)
        except GitHubAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @fastapi_app.get("/v1/dashboard", response_model=OrgDashboardSummary)
    def dashboard_endpoint(
        repo_root: str = ".",
        prd_path: str = "PROJECT_SPEC.md",
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> OrgDashboardSummary:
        org_id = _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        repo_path = _resolve_allowed_repo_root(
            repo_root, allowed_workspace_root, org_id, org_registry
        )
        prd_file = (repo_path / prd_path).resolve()
        prd_markdown = (
            prd_file.read_text(encoding="utf-8")
            if prd_file.is_relative_to(repo_path) and prd_file.is_file()
            else ""
        )
        repo_map = cache.get_or_index(repo_path, scope=org_id or "")
        flags = extract_feature_flags(repo_path)
        drift_report = check_spec_drift(
            prd_markdown,
            repo_map,
            prd_path=prd_path,
            repo_root=repo_path,
        )
        scope_coverage = compute_scope_coverage(prd_markdown, repo_map)
        checklist = generate_edge_case_checklist(
            repo_map,
            prd_markdown=prd_markdown or None,
            repo_root=repo_path,
        )
        return OrgDashboardSummary(
            repo_root=repo_map.repo_root,
            models_count=len(repo_map.models),
            routes_count=len(repo_map.routes),
            telemetry_count=len(repo_map.telemetry),
            adrs_count=len(repo_map.adrs),
            feature_flags_count=len(flags),
            alignment_score=drift_report.alignment_score.overall_score,
            scope_coverage_percent=scope_coverage.coverage_percent,
            p0_checklist_items=checklist.p0_count,
            status=drift_report.status,
        )

    @fastapi_app.post("/v1/publish", response_model=PublishResult)
    def publish_endpoint(
        payload: PublishCommentRequest,
        authorization: str = Header(default="", alias="Authorization"),
        x_pmcursor_token: str = Header(default="", alias="X-PMCursor-Token"),
    ) -> PublishResult:
        _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        try:
            return _dispatch_publish(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @fastapi_app.post("/v1/webhooks/github")
    async def github_webhook(
        request: WebhookRequest,
        background_tasks: BackgroundTasks,
        x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
        x_github_delivery: str = Header(default="", alias="X-GitHub-Delivery"),
        x_github_event: str = Header(default="", alias="X-GitHub-Event"),
    ) -> PRImpactReport | dict[str, Any]:
        payload_body = await _read_bounded_webhook_body(request)
        secret = (
            webhook_secret
            if webhook_secret is not None
            else os.environ.get("PMCURSOR_WEBHOOK_SECRET", "")
        )
        if not verify_github_signature(payload_body, x_hub_signature_256, secret):
            _audit("webhook_signature_invalid", provider="github")
            raise HTTPException(
                status_code=401, detail="Invalid GitHub webhook signature"
            )
        if (dup := _check_duplicate_delivery("github", x_github_delivery)) is not None:
            return dup
        try:
            content_type = request.headers.get("content-type", "")
            data = _decode_webhook_json(payload_body, content_type)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if isinstance(data, dict):
            if "zen" in data:
                return {"status": "pong", "hook_id": data.get("hook_id")}
            automation_events = (
                ("pull_request" in data and "prd_markdown" not in data)
                or "merge_group" in data
                or "check_run" in data
            )
            if automation_events:
                repo = data.get("repository")
                repo_name = repo.get("full_name") if isinstance(repo, dict) else None
                action = data.get("action")
                response: dict[str, Any] = {
                    "status": "accepted",
                    "action": action,
                    "pr_number": data.get("number"),
                    "repository": repo_name,
                }
                check_run = data.get("check_run")
                eligible = (
                    ("pull_request" in data and action in PR_AUTOMATION_ACTIONS)
                    or ("merge_group" in data and action == "checks_requested")
                    or (
                        isinstance(check_run, dict)
                        and action == "rerequested"
                        and check_run.get("name") == DEFAULT_CHECK_RUN_NAME
                    )
                )
                if (
                    eligible
                    and effective_github_app is not None
                    and effective_pr_automation
                    and isinstance(data.get("installation"), dict)
                ):
                    try:
                        pr_client = build_repo_client(
                            data,
                            github_app=effective_github_app,
                            api_base=effective_github_api_base,
                        )
                    except GitHubAutomationError:
                        response["automation"] = "skipped:no-installation"
                    else:
                        raw_prd = os.environ.get("PMCURSOR_PRD_PATH", "")
                        prd_candidates = tuple(
                            p.strip() for p in raw_prd.split(",") if p.strip()
                        ) or DEFAULT_PRD_CANDIDATES
                        background_tasks.add_task(
                            run_pull_request_automation,
                            data,
                            client=pr_client,
                            prd_candidates=prd_candidates,
                            post_failure_comment=effective_pr_comments,
                        )
                        response["automation"] = "queued"
                return response
            if x_github_event in {
                "installation",
                "installation_repositories",
                "installation_target",
            }:
                installation = data.get("installation")
                install_id = (
                    installation.get("id")
                    if isinstance(installation, dict)
                    else None
                )
                return {
                    "status": "accepted",
                    "event": x_github_event,
                    "action": data.get("action"),
                    "installation_id": install_id,
                }
        try:
            payload = GitHubWebhookPayload.model_validate(data)
            root = Path(payload.repo_root).resolve()
            if (
                allowed_workspace_root is not None
                and not root.is_relative_to(allowed_workspace_root.resolve())
            ):
                raise PermissionError("Repository root outside allowed workspace")
            repo_map = cache.get_or_index(root)
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
        linear_delivery: str = Header(default="", alias="Linear-Delivery"),
    ) -> TicketSyncReport | dict[str, Any]:
        payload_body = await _read_bounded_webhook_body(request)
        secret = (
            linear_webhook_secret
            if linear_webhook_secret is not None
            else os.environ.get("PMCURSOR_LINEAR_WEBHOOK_SECRET", "")
        )
        if not verify_linear_signature(payload_body, linear_signature, secret):
            _audit("webhook_signature_invalid", provider="linear")
            raise HTTPException(
                status_code=401, detail="Invalid Linear webhook signature"
            )
        if (dup := _check_duplicate_delivery("linear", linear_delivery)) is not None:
            return dup
        data, root = _parse_webhook_dict_and_repo(
            payload_body,
            request.headers.get("content-type", ""),
            allowed_workspace_root,
        )
        parsed = parse_linear_webhook_issue(data)
        if parsed is None:
            return {"status": "ignored", "event_type": data.get("type")}
        ticket_id, title, description = parsed
        repo_map = cache.get_or_index(root)
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
        x_atlassian_webhook_identifier: str = Header(
            default="", alias="X-Atlassian-Webhook-Identifier"
        ),
    ) -> TicketSyncReport | dict[str, Any]:
        payload_body = await _read_bounded_webhook_body(request)
        jira_secret = (
            jira_webhook_secret
            if jira_webhook_secret is not None
            else os.environ.get("PMCURSOR_JIRA_WEBHOOK_SECRET", "")
        )
        if jira_secret:
            if not verify_jira_signature(payload_body, x_hub_signature, jira_secret):
                _audit("webhook_signature_invalid", provider="jira")
                raise HTTPException(
                    status_code=401, detail="Invalid Jira webhook signature"
                )
        else:
            _require_auth(api_token, authorization, x_pmcursor_token, org_registry)
        if (
            dup := _check_duplicate_delivery("jira", x_atlassian_webhook_identifier)
        ) is not None:
            return dup
        data, root = _parse_webhook_dict_and_repo(
            payload_body,
            request.headers.get("content-type", ""),
            allowed_workspace_root,
        )
        parsed = parse_jira_webhook_issue(data)
        if parsed is None:
            return {"status": "ignored", "webhook_event": data.get("webhookEvent")}
        ticket_id, title, description = parsed
        repo_map = cache.get_or_index(root)
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
        org_backend = os.environ.get(ENV_ORG_BACKEND, "").strip().lower()
        if os.environ.get("PMCURSOR_ORG_STORE", "").strip() and org_backend != "sqlite":
            raise ValueError(
                "Refusing to start with WEB_CONCURRENCY>1 while PMCURSOR_ORG_STORE uses "
                "the file backend: it is single-writer and worker processes would clobber "
                "each other's updates. Set PMCURSOR_ORG_BACKEND=sqlite for multi-worker "
                "deployments, or run one worker per node."
            )
        logger.warning(
            "WEB_CONCURRENCY>1: rate limiting, index cache, and webhook deduplication are "
            "per-process — limits and dedup apply per worker, not per deployment."
        )
        uvicorn_module.run("api.server:app", host=host, port=port, workers=workers)
    else:
        uvicorn_module.run(app, host=host, port=port)
