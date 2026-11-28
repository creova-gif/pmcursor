from __future__ import annotations

import hashlib
import hmac
import io
import json
import sys
import types
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from pmcursor.cli import main as cli_main
from pmcursor.github_app import (
    GitHubAppAuth,
    GitHubAppCredentials,
    GitHubAppError,
    GitHubInstallationToken,
    build_app_manifest,
    default_github_app,
    exchange_manifest_code,
)


def _urlopen_returning(payload: bytes, calls: list[urllib.request.Request]) -> Any:
    def fake_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> MagicMock:
        calls.append(req)
        resp = MagicMock()
        resp.read.return_value = payload
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    return fake_urlopen


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_build_app_manifest_fields() -> None:
    manifest = build_app_manifest(
        name="pmcursor-drift",
        webhook_url="https://pm.example.com/v1/webhooks/github",
        redirect_url="https://pm.example.com/installed",
    )
    assert manifest["name"] == "pmcursor-drift"
    assert manifest["hook_attributes"]["url"] == (
        "https://pm.example.com/v1/webhooks/github"
    )
    assert manifest["hook_attributes"]["active"] is True
    assert manifest["redirect_url"] == "https://pm.example.com/installed"
    assert manifest["public"] is False
    assert manifest["default_permissions"]["pull_requests"] == "write"
    assert manifest["default_permissions"]["checks"] == "write"
    assert manifest["default_permissions"]["contents"] == "read"
    assert manifest["default_permissions"]["issues"] == "write"
    assert manifest["default_permissions"]["merge_queues"] == "read"
    assert manifest["default_events"] == [
        "pull_request",
        "push",
        "check_run",
        "merge_group",
    ]


def test_build_app_manifest_requires_webhook_url() -> None:
    with pytest.raises(GitHubAppError, match="webhook_url"):
        build_app_manifest(webhook_url="")


def test_build_app_manifest_rejects_private_webhook_url() -> None:
    with pytest.raises(ValueError):
        build_app_manifest(webhook_url="http://localhost:8000/hook")


def test_exchange_manifest_code_parses_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[urllib.request.Request] = []
    payload = json.dumps(
        {
            "id": 123456,
            "slug": "pmcursor-drift",
            "name": "pmcursor-drift",
            "client_id": "Iv1.abc",
            "client_secret": "secret",
            "webhook_secret": "whsec",
            "pem": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        }
    ).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_returning(payload, calls))
    creds = exchange_manifest_code("code-xyz")
    assert isinstance(creds, GitHubAppCredentials)
    assert creds.app_id == 123456
    assert creds.slug == "pmcursor-drift"
    assert calls[0].full_url.endswith("/app-manifests/code-xyz/conversions")
    assert calls[0].method == "POST"


def test_exchange_manifest_code_empty_code() -> None:
    with pytest.raises(GitHubAppError, match="empty"):
        exchange_manifest_code("  ")


def test_exchange_manifest_code_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> Any:
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", Message(), io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    with pytest.raises(GitHubAppError, match="HTTP 404"):
        exchange_manifest_code("bad-code")


def test_github_app_auth_validates_config() -> None:
    with pytest.raises(GitHubAppError, match="app_id"):
        GitHubAppAuth(app_id=0, private_key_pem="pem")
    with pytest.raises(GitHubAppError, match="private_key_pem"):
        GitHubAppAuth(app_id=1, private_key_pem="  ")


def _install_fake_jwt(monkeypatch: pytest.MonkeyPatch, token: str = "signed-jwt") -> None:
    jwt_mod = types.ModuleType("jwt")

    def _encode(payload: dict[str, Any], key: str, algorithm: str) -> str:
        assert algorithm == "RS256"
        assert payload["exp"] - payload["iat"] == 660
        return token

    jwt_mod.encode = _encode  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "jwt", jwt_mod)


def test_installation_token_mints_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_jwt(monkeypatch)
    calls: list[urllib.request.Request] = []
    payload = json.dumps(
        {"token": "ghs_install_token", "expires_at": "2027-01-01T00:00:00Z"}
    ).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_returning(payload, calls))
    auth = GitHubAppAuth(
        app_id=42, private_key_pem="fake-pem", allow_private_urls=True
    )
    first = auth.installation_token(7)
    second = auth.installation_token(7)
    assert isinstance(first, GitHubInstallationToken)
    assert first.token == "ghs_install_token"
    assert first.expires_at == "2027-01-01T00:00:00Z"
    assert second.token == first.token
    assert len(calls) == 1
    assert "/app/installations/7/access_tokens" in calls[0].full_url
    assert calls[0].get_header("Authorization") == "Bearer signed-jwt"


def test_installation_token_invalid_id() -> None:
    auth = GitHubAppAuth(app_id=1, private_key_pem="pem")
    with pytest.raises(GitHubAppError, match="installation_id"):
        auth.installation_token(0)


def test_default_github_app_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY_PATH", raising=False)
    assert default_github_app() is None


def test_default_github_app_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pem_file = tmp_path / "app.pem"
    pem_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nk\n-----END RSA PRIVATE KEY-----\n")
    monkeypatch.setenv("PMCURSOR_GITHUB_APP_ID", "99")
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY_PATH", str(pem_file))
    auth = default_github_app()
    assert isinstance(auth, GitHubAppAuth)


def test_default_github_app_bad_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PMCURSOR_GITHUB_APP_ID", "not-an-int")
    monkeypatch.setenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY", "pem")
    with pytest.raises(GitHubAppError, match="not an integer"):
        default_github_app()


def test_api_manifest_endpoint() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get(
        "/v1/github-app/manifest",
        params={"webhook_url": "https://pm.example.com/v1/webhooks/github"},
    )
    assert resp.status_code == 200
    assert resp.json()["hook_attributes"]["url"] == (
        "https://pm.example.com/v1/webhooks/github"
    )


def test_api_manifest_endpoint_requires_webhook_url() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/v1/github-app/manifest")
    assert resp.status_code == 422


def test_api_manifest_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_exchange(code: str, **kwargs: Any) -> GitHubAppCredentials:
        assert code == "the-code"
        return GitHubAppCredentials(
            app_id=1,
            slug="app",
            name="app",
            client_id="cid",
            client_secret="cs",
            webhook_secret="ws",
            pem="pem",
        )

    monkeypatch.setattr("api.server.exchange_manifest_code", fake_exchange)
    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/v1/github-app/manifest/conversions", json={"code": "the-code"}
    )
    assert resp.status_code == 200
    assert resp.json()["app_id"] == 1


def test_api_installation_token_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY_PATH", raising=False)
    app = create_app()
    client = TestClient(app)
    resp = client.post("/v1/github-app/installations/7/token")
    assert resp.status_code == 503


def test_api_installation_token_with_stub() -> None:
    class _StubAuth:
        def installation_token(self, installation_id: int) -> GitHubInstallationToken:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token="ghs_x",
                expires_at="2027-01-01T00:00:00Z",
            )

    app = create_app(github_app=_StubAuth())  # type: ignore[arg-type]
    client = TestClient(app)
    resp = client.post("/v1/github-app/installations/55/token")
    assert resp.status_code == 200
    assert resp.json()["installation_id"] == 55
    assert resp.json()["token"] == "ghs_x"


def test_webhook_installation_event_accepted() -> None:
    secret = "wh-secret"
    body = json.dumps(
        {
            "action": "created",
            "installation": {"id": 4242, "account": {"login": "acme"}},
        }
    ).encode("utf-8")
    app = create_app(webhook_secret=secret)
    client = TestClient(app)
    resp = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, secret),
            "X-GitHub-Event": "installation",
            "X-GitHub-Delivery": "deliv-1",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["event"] == "installation"
    assert data["installation_id"] == 4242


def test_webhook_installation_event_still_requires_signature() -> None:
    body = json.dumps({"action": "created", "installation": {"id": 1}}).encode(
        "utf-8"
    )
    app = create_app(webhook_secret="wh-secret")
    client = TestClient(app)
    resp = client.post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=bad",
            "X-GitHub-Event": "installation",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


def test_cli_github_app_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(
        [
            "github-app",
            "manifest",
            "--webhook-url",
            "https://pm.example.com/v1/webhooks/github",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["name"] == "pmcursor-drift"
    assert out["hook_attributes"]["url"].endswith("/v1/webhooks/github")


def test_cli_github_app_manifest_missing_url(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(["github-app", "manifest"])
    assert rc == 2
    assert "--webhook-url" in capsys.readouterr().err


def test_cli_github_app_token_unconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PMCURSOR_GITHUB_APP_PRIVATE_KEY_PATH", raising=False)
    rc = cli_main(["github-app", "token", "--installation-id", "5"])
    assert rc == 2
    assert "not configured" in capsys.readouterr().err
