from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from pmcursor.publisher import _validate_outbound_url

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
_JWT_TTL_SECONDS = 600
_JWT_IAT_BACKDATE_SECONDS = 60
_TOKEN_REFRESH_MARGIN_SECONDS = 60


class GitHubAppError(RuntimeError):
    """Raised when a GitHub App operation cannot be completed."""


class GitHubAppCredentials(BaseModel):
    """Credentials returned by the GitHub App manifest conversion flow.

    `pem` is the app private key — treat the whole model as a secret.
    """

    model_config = ConfigDict(frozen=True)

    app_id: int
    slug: str
    name: str
    client_id: str
    client_secret: str
    webhook_secret: str
    pem: str


class GitHubInstallationToken(BaseModel):
    """A short-lived installation access token for a GitHub App."""

    model_config = ConfigDict(frozen=True)

    installation_id: int
    token: str
    expires_at: str


def build_app_manifest(
    *,
    name: str = "pmcursor-drift",
    webhook_url: str,
    redirect_url: str | None = None,
    homepage_url: str = "https://github.com/creova-gif/pmcursor",
    description: str = (
        "PMCursor spec-vs-code drift audits: posts drift findings and "
        "checklist evidence on pull requests."
    ),
    public: bool = False,
) -> dict[str, Any]:
    """Build a GitHub App creation manifest.

    POST the returned JSON as the `manifest` field to
    `https://github.com/settings/apps/new` (browser) to create the app;
    GitHub redirects to `redirect_url` with a `code` that
    `exchange_manifest_code` converts into app credentials.
    """
    if not webhook_url.strip():
        raise GitHubAppError("webhook_url is required for the app manifest")
    _validate_outbound_url(webhook_url)
    manifest: dict[str, Any] = {
        "name": name,
        "url": homepage_url,
        "description": description,
        "public": public,
        "hook_attributes": {"url": webhook_url, "active": True},
        "default_permissions": {
            "contents": "read",
            "pull_requests": "write",
            "issues": "write",
            "checks": "write",
            "merge_queues": "read",
        },
        "default_events": [
            "pull_request",
            "push",
            "check_run",
            "merge_group",
        ],
    }
    if redirect_url:
        _validate_outbound_url(redirect_url)
        manifest["redirect_url"] = redirect_url
    return manifest


def _post_json(
    url: str,
    *,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
    timeout_seconds: float,
    allow_private_urls: bool,
) -> dict[str, Any]:
    _validate_outbound_url(url, allow_private_urls=allow_private_urls)
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — URL validated above
        url,
        data=body,
        headers={"Accept": "application/vnd.github+json", **headers},
        method="POST",
    )
    try:
        # URL scheme & SSRF safety verified above via _validate_outbound_url.
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise GitHubAppError(
            f"GitHub API returned HTTP {exc.code} for {url!r}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubAppError(
            f"GitHub API unreachable for {url!r}: {exc.reason}"
        ) from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubAppError(
            f"GitHub API returned non-JSON response for {url!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise GitHubAppError(
            f"GitHub API returned unexpected payload for {url!r}"
        )
    return parsed


def exchange_manifest_code(
    code: str,
    *,
    api_base: str = GITHUB_API_BASE,
    timeout_seconds: float = 15.0,
    allow_private_urls: bool = False,
) -> GitHubAppCredentials:
    """Exchange an app-manifest `code` for app credentials.

    Called after GitHub redirects the browser to the manifest's
    `redirect_url` with `?code=...`.
    """
    if not code.strip():
        raise GitHubAppError("Manifest conversion code is empty")
    url = f"{api_base.rstrip('/')}/app-manifests/{code}/conversions"
    payload = _post_json(
        url,
        payload=None,
        headers={},
        timeout_seconds=timeout_seconds,
        allow_private_urls=allow_private_urls,
    )
    try:
        return GitHubAppCredentials(
            app_id=int(payload["id"]),
            slug=str(payload["slug"]),
            name=str(payload["name"]),
            client_id=str(payload["client_id"]),
            client_secret=str(payload["client_secret"]),
            webhook_secret=str(payload["webhook_secret"]),
            pem=str(payload["pem"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubAppError(
            "GitHub manifest conversion response missing expected fields"
        ) from exc


class GitHubAppAuth:
    """Mints and caches installation access tokens for a GitHub App.

    Requires `pmcursor[github-app]` (PyJWT with crypto support) for the
    RS256 JWT the app uses to authenticate as itself.
    """

    def __init__(
        self,
        *,
        app_id: int,
        private_key_pem: str,
        api_base: str = GITHUB_API_BASE,
        timeout_seconds: float = 15.0,
        allow_private_urls: bool = False,
    ) -> None:
        if app_id <= 0:
            raise GitHubAppError("app_id must be a positive integer")
        if not private_key_pem.strip():
            raise GitHubAppError("private_key_pem is empty")
        self._app_id = app_id
        self._private_key_pem = private_key_pem
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._allow_private_urls = allow_private_urls
        self._token_cache: dict[int, tuple[str, float]] = {}

    def _jwt(self) -> str:
        try:
            import jwt
        except ModuleNotFoundError as exc:
            raise GitHubAppError(
                "PyJWT is required for GitHub App authentication. "
                "Install with: pip install 'pmcursor[github-app]'"
            ) from exc
        now = int(time.time())
        payload = {
            "iat": now - _JWT_IAT_BACKDATE_SECONDS,
            "exp": now + _JWT_TTL_SECONDS,
            "iss": str(self._app_id),
        }
        try:
            token = jwt.encode(payload, self._private_key_pem, algorithm="RS256")
        except Exception as exc:
            raise GitHubAppError(
                "Failed to sign GitHub App JWT; check private_key_pem"
            ) from exc
        return token if isinstance(token, str) else token.decode("utf-8")

    def installation_token(self, installation_id: int) -> GitHubInstallationToken:
        """Return a valid installation token, minting one if needed."""
        if installation_id <= 0:
            raise GitHubAppError("installation_id must be a positive integer")
        cached = self._token_cache.get(installation_id)
        now = time.time()
        if cached and cached[1] - now > _TOKEN_REFRESH_MARGIN_SECONDS:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token=cached[0],
                expires_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(cached[1])
                ),
            )
        app_jwt = self._jwt()
        url = f"{self._api_base}/app/installations/{installation_id}/access_tokens"
        payload = _post_json(
            url,
            payload={},
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout_seconds=self._timeout_seconds,
            allow_private_urls=self._allow_private_urls,
        )
        token = payload.get("token")
        expires_at = payload.get("expires_at")
        if not isinstance(token, str) or not token:
            raise GitHubAppError(
                "GitHub installation token response missing 'token'"
            )
        expires_epoch = now + 3600
        if isinstance(expires_at, str):
            try:
                expires_epoch = time.mktime(
                    time.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ")
                ) - time.timezone
            except ValueError:
                logger.debug("Unparseable expires_at %r; assuming 1h", expires_at)
        self._token_cache[installation_id] = (token, expires_epoch)
        return GitHubInstallationToken(
            installation_id=installation_id,
            token=token,
            expires_at=expires_at if isinstance(expires_at, str) else "",
        )


def default_github_app() -> GitHubAppAuth | None:
    """Build a GitHubAppAuth from the environment, or None if unconfigured.

    Reads `PMCURSOR_GITHUB_APP_ID` plus `PMCURSOR_GITHUB_APP_PRIVATE_KEY`
    (inline PEM, `\\n` escapes allowed) or
    `PMCURSOR_GITHUB_APP_PRIVATE_KEY_PATH`.
    """
    app_id_raw = os.environ.get("PMCURSOR_GITHUB_APP_ID", "").strip()
    pem = os.environ.get("PMCURSOR_GITHUB_APP_PRIVATE_KEY", "")
    if not pem:
        pem_path = os.environ.get("PMCURSOR_GITHUB_APP_PRIVATE_KEY_PATH", "")
        if pem_path:
            pem = Path(pem_path).read_text(encoding="utf-8")
    pem = pem.replace("\\n", "\n")
    if not app_id_raw or not pem.strip():
        return None
    try:
        app_id = int(app_id_raw)
    except ValueError as exc:
        raise GitHubAppError(
            f"PMCURSOR_GITHUB_APP_ID {app_id_raw!r} is not an integer"
        ) from exc
    api_base = os.environ.get("PMCURSOR_GITHUB_API_BASE", GITHUB_API_BASE)
    return GitHubAppAuth(
        app_id=app_id, private_key_pem=pem, api_base=api_base
    )
