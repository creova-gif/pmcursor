from __future__ import annotations

import ipaddress
import json
import time
import urllib.error
import urllib.request
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

PublishProvider = Literal["github", "linear", "jira"]

_RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 502, 503, 504})

_LINEAR_COMMENT_MUTATION = """
mutation CommentCreate($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) {
    success
  }
}
""".strip()


class PublishResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: PublishProvider
    target_id: str
    dry_run: bool
    status_code: int
    url: str
    body_preview: str


def _validate_outbound_url(url: str, *, allow_private_urls: bool = False) -> None:
    """Validate an outbound webhook/API URL against SSRF and embedded credentials."""
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError(
            f"Outbound URL must use https:// or http:// with a valid hostname, got: {url!r}"
        )
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Outbound URL must not contain embedded credentials")

    if not allow_private_urls:
        if parsed.scheme != "https":
            raise ValueError("Outbound URL must use https:// unless allow_private_urls=True")
        hostname = parsed.hostname.lower().rstrip(".")
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
            raise ValueError(f"Outbound URL must not target local hostnames: {hostname!r}")
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            ip = None
        if ip is not None and (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                f"Outbound URL must not target private or reserved IP addresses: {hostname!r}"
            )


def _preview_body(body: str, limit: int = 120) -> str:
    if len(body) <= limit:
        return body
    return f"{body[: limit - 3]}..."


def _post_json(
    *,
    provider: PublishProvider,
    target_id: str,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    body_text: str,
    token: str | None,
    dry_run: bool,
    max_retries: int = 2,
    retry_delay_seconds: float = 0.25,
    allow_private_urls: bool = False,
) -> PublishResult:
    _validate_outbound_url(url, allow_private_urls=allow_private_urls)
    preview = _preview_body(body_text)
    if dry_run:
        return PublishResult(
            provider=provider,
            target_id=target_id,
            dry_run=True,
            status_code=0,
            url=url,
            body_preview=preview,
        )

    if token is None or not token.strip():
        raise ValueError(f"Missing authentication token for {provider} publish.")
    if max_retries < 0:
        raise ValueError(f"max_retries must be non-negative, got: {max_retries}")

    data = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url=url, data=data, headers=request_headers, method="POST")

    status_code = 0
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = int(getattr(resp, "status", 200))
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_HTTP_STATUS_CODES or attempt >= max_retries:
                raise RuntimeError(
                    f"{provider} API returned HTTP {exc.code}: {exc.reason}"
                ) from exc
        except urllib.error.URLError:
            if attempt >= max_retries:
                raise

        if retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds * (2**attempt))

    return PublishResult(
        provider=provider,
        target_id=target_id,
        dry_run=False,
        status_code=status_code,
        url=url,
        body_preview=preview,
    )


def publish_github_pr_comment(
    repo_full_name: str,
    pr_number: int,
    body: str,
    *,
    token: str | None = None,
    dry_run: bool = False,
    api_base: str = "https://api.github.com",
    max_retries: int = 2,
    retry_delay_seconds: float = 0.25,
    allow_private_urls: bool = False,
) -> PublishResult:
    """Post a comment on a GitHub pull request via the Issues Comments API."""
    url = f"{api_base.rstrip('/')}/repos/{repo_full_name}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token.strip() if token else ''}",
        "Accept": "application/vnd.github+json",
    }
    return _post_json(
        provider="github",
        target_id=f"{repo_full_name}#{pr_number}",
        url=url,
        payload={"body": body},
        headers=headers,
        body_text=body,
        token=token,
        dry_run=dry_run,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        allow_private_urls=allow_private_urls,
    )


def publish_linear_comment(
    issue_id: str,
    body: str,
    *,
    api_key: str | None = None,
    dry_run: bool = False,
    endpoint: str = "https://api.linear.app/graphql",
    max_retries: int = 2,
    retry_delay_seconds: float = 0.25,
    allow_private_urls: bool = False,
) -> PublishResult:
    """Post a comment on a Linear issue via the GraphQL commentCreate mutation."""
    headers = {"Authorization": api_key.strip() if api_key else ""}
    payload: dict[str, Any] = {
        "query": _LINEAR_COMMENT_MUTATION,
        "variables": {"issueId": issue_id, "body": body},
    }
    return _post_json(
        provider="linear",
        target_id=issue_id,
        url=endpoint,
        payload=payload,
        headers=headers,
        body_text=body,
        token=api_key,
        dry_run=dry_run,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        allow_private_urls=allow_private_urls,
    )


def publish_jira_comment(
    base_url: str,
    issue_key: str,
    body: str,
    *,
    bearer_token: str | None = None,
    dry_run: bool = False,
    max_retries: int = 2,
    retry_delay_seconds: float = 0.25,
    allow_private_urls: bool = False,
) -> PublishResult:
    """Post a comment on a Jira issue via the REST v2 issue comment endpoint."""
    url = f"{base_url.rstrip('/')}/rest/api/2/issue/{issue_key}/comment"
    headers = {"Authorization": f"Bearer {bearer_token.strip() if bearer_token else ''}"}
    return _post_json(
        provider="jira",
        target_id=issue_key,
        url=url,
        payload={"body": body},
        headers=headers,
        body_text=body,
        token=bearer_token,
        dry_run=dry_run,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        allow_private_urls=allow_private_urls,
    )
