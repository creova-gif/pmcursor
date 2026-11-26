from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

PublishProvider = Literal["github", "linear", "jira"]

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


def _validate_http_url(url: str) -> None:
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"URL must start with https:// or http://, got: {url!r}")


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
) -> PublishResult:
    _validate_http_url(url)
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

    data = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url=url, data=data, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status_code = int(getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{provider} API returned HTTP {exc.code}: {exc.reason}") from exc

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
    )


def publish_linear_comment(
    issue_id: str,
    body: str,
    *,
    api_key: str | None = None,
    dry_run: bool = False,
    endpoint: str = "https://api.linear.app/graphql",
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
    )


def publish_jira_comment(
    base_url: str,
    issue_key: str,
    body: str,
    *,
    bearer_token: str | None = None,
    dry_run: bool = False,
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
    )
