from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import sys
import tarfile
import types
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Self

import pytest
from fastapi.testclient import TestClient

import api.server as server_module
from api.server import create_app
from pmcursor.github_app import GitHubAppAuth, GitHubInstallationToken
from pmcursor.github_pr_automation import (
    GitHubAutomationError,
    GitHubRepoClient,
    _extract_tarball,
    build_repo_client,
    check_run_conclusion,
    process_pull_request_event,
    run_pull_request_automation,
)
from pmcursor.models import (
    DriftFinding,
    DriftReport,
    SpecAlignmentScore,
)

_FAKE_API = "https://api.github.test"
_SECRET = "whsec"


class _Resp:
    """Context-manager response over bytes, mimicking addinfourl."""

    def __init__(self, raw: bytes) -> None:
        self._bio = io.BytesIO(raw)

    def read(self, n: int = -1) -> bytes:
        return self._bio.read(n)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _json_resp(payload: dict[str, Any]) -> _Resp:
    return _Resp(json.dumps(payload).encode("utf-8"))


def _http_404(url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url, 404, "Not Found", None, io.BytesIO(b"")  # type: ignore[arg-type]
    )


def _make_tarball(files: dict[str, str], root: str = "octo-repo-abc123") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            raw = content.encode("utf-8")
            info = tarfile.TarInfo(f"{root}/{path}")
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


class _FakeGitHub:
    """urlopen replacement routing by URL path; records check-run posts."""

    def __init__(
        self,
        *,
        tarball: bytes,
        contents: dict[str, str],
        diff: bytes = b"",
        comments: list[dict[str, Any]] | None = None,
    ) -> None:
        self.tarball = tarball
        self.contents = contents
        self.diff = diff
        self.comments = comments or []
        self.check_runs: list[dict[str, Any]] = []
        self.created_comments: list[dict[str, Any]] = []
        self.updated_comments: list[tuple[int, dict[str, Any]]] = []
        self.urls: list[str] = []

    def __call__(
        self, req: urllib.request.Request, timeout: float = 30.0
    ) -> _Resp:
        url = req.full_url
        self.urls.append(url)
        if "/access_tokens" in url:
            return _json_resp(
                {"token": "ghs_install_token", "expires_at": "2027-01-01T00:00:00Z"}
            )
        if "/tarball/" in url:
            return _Resp(self.tarball)
        if "/contents/" in url:
            path = url.split("/contents/", 1)[1].split("?", 1)[0]
            if path in self.contents:
                return _json_resp(
                    {
                        "content": base64.b64encode(
                            self.contents[path].encode("utf-8")
                        ).decode("ascii"),
                        "encoding": "base64",
                    }
                )
            raise _http_404(url)
        if "/compare/" in url:
            return _Resp(self.diff)
        if "/issues/comments/" in url and req.get_method() == "PATCH":
            comment_id = int(url.rstrip("/").split("/")[-1])
            if isinstance(req.data, bytes):
                body = json.loads(req.data.decode("utf-8"))
            else:
                body = {}
            self.updated_comments.append((comment_id, body))
            return _json_resp({"id": comment_id})
        if "/issues/" in url and "/comments" in url:
            if req.get_method() == "GET":
                return _Resp(json.dumps(self.comments).encode("utf-8"))
            if isinstance(req.data, bytes):
                body = json.loads(req.data.decode("utf-8"))
            else:
                body = {}
            self.created_comments.append(body)
            return _json_resp({"id": 999})
        if "/check-runs" in url and isinstance(req.data, bytes):
            self.check_runs.append(json.loads(req.data.decode("utf-8")))
            return _json_resp({"id": 1})
        raise AssertionError(f"unexpected GitHub request: {url}")


def _install_fake_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    jwt_mod = types.ModuleType("jwt")

    def _encode(payload: dict[str, Any], key: str, algorithm: str) -> str:
        return "signed-jwt"

    jwt_mod.encode = _encode  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "jwt", jwt_mod)


def _auth() -> GitHubAppAuth:
    return GitHubAppAuth(
        app_id=42,
        private_key_pem="fake-pem",
        api_base=_FAKE_API,
        allow_private_urls=True,
    )


def _client() -> GitHubRepoClient:
    return GitHubRepoClient(
        auth=_auth(), installation_id=7, api_base=_FAKE_API
    )


def _pr_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "opened",
        "number": 5,
        "repository": {"full_name": "octo/repo", "default_branch": "main"},
        "pull_request": {
            "head": {"sha": "abc123def", "ref": "feat/x"},
            "base": {"sha": "def456abc", "ref": "main"},
        },
        "installation": {"id": 7},
    }
    payload.update(overrides)
    return payload


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def _report(
    status: str,
    *,
    findings: list[DriftFinding] | None = None,
    fabricated: int = 0,
) -> DriftReport:
    return DriftReport(
        prd_path="PRD.md",
        status=status,  # type: ignore[arg-type]
        alignment_score=SpecAlignmentScore(
            overall_score=50,
            deterministic_score=50,
            workflow_score=50,
            has_acceptance_cards=False,
            has_rollback_section=False,
            has_out_of_scope_section=False,
            has_adr_references=False,
        ),
        total_spec_contracts=2,
        matched_contracts=1,
        total_citations_checked=1,
        fabricated_citations_count=fabricated,
        findings=findings or [],
    )


_REPO_FILES = {
    "app/models.py": (
        "from pydantic import BaseModel\n\n"
        "class User(BaseModel):\n"
        "    id: int\n"
        "    email: str\n"
    ),
}

_PRD = "# Spec\n\nThe User model stores account data.\n"
_PRD_FABRICATED = (
    "# Spec\n\nUser model is defined at app/models.py:99.\n"
    "See also docs/nothing.md:1.\n"
)
_DIFF = (
    "diff --git a/app/models.py b/app/models.py\n"
    "--- a/app/models.py\n"
    "+++ b/app/models.py\n"
    "@@ -1,4 +1,5 @@\n"
    " class User(BaseModel):\n"
    "     id: int\n"
    "     email: str\n"
    "+    is_active: bool = True\n"
)


def test_build_repo_client_requires_installation() -> None:
    payload = _pr_payload()
    del payload["installation"]
    with pytest.raises(GitHubAutomationError, match="installation.id"):
        build_repo_client(payload, github_app=_auth())


def test_fetch_file_decodes_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(tarball=b"", contents={"PRD.md": _PRD})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    text = _client().fetch_file("octo/repo", "PRD.md", "abc123def")
    assert text == _PRD


def test_fetch_file_missing_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(tarball=b"", contents={})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    assert _client().fetch_file("octo/repo", "PRD.md", "abc123def") is None


def test_fetch_compare_diff_truncates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(tarball=b"", contents={}, diff=b"x" * 4096)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    client = GitHubRepoClient(
        auth=_auth(),
        installation_id=7,
        api_base=_FAKE_API,
        max_diff_bytes=1024,
    )
    diff = client.fetch_compare_diff("octo/repo", "def456abc", "abc123def")
    assert "diff truncated" in diff
    assert len(diff) < 4096
    assert "/compare/def456abc...abc123def" in fake.urls[-1]


def test_check_run_conclusion_mapping() -> None:
    critical = DriftFinding(
        category="missing_model",
        severity="critical",
        spec_reference="PRD.md:1",
        message="gone",
        remediation="add it",
    )
    assert check_run_conclusion(_report("DONE")) == "success"
    assert check_run_conclusion(_report("DONE_WITH_CONCERNS")) == "neutral"
    assert check_run_conclusion(_report("BLOCKED")) == "failure"
    assert check_run_conclusion(_report("DONE", fabricated=1)) == "failure"
    assert (
        check_run_conclusion(_report("DONE", findings=[critical])) == "failure"
    )


def test_process_pull_request_event_posts_check_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(
        tarball=_make_tarball(_REPO_FILES),
        contents={"PROJECT_SPEC.md": _PRD},
        diff=_DIFF.encode("utf-8"),
    )
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = process_pull_request_event(_pr_payload(), client=_client())
    assert result.status == "completed"
    assert result.repository == "octo/repo"
    assert result.pr_number == 5
    assert result.head_sha == "abc123def"
    assert len(fake.check_runs) == 1
    run = fake.check_runs[0]
    assert run["head_sha"] == "abc123def"
    assert run["status"] == "completed"
    assert run["conclusion"] in {"success", "failure", "neutral"}
    assert run["output"]["title"].startswith("PMCursor drift")


def test_process_pull_request_event_empty_prd_posts_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(
        tarball=_make_tarball(_REPO_FILES),
        contents={"PROJECT_SPEC.md": ""},
    )
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = process_pull_request_event(_pr_payload(), client=_client())
    assert result.status == "skipped"
    assert fake.check_runs[0]["conclusion"] == "neutral"


def test_process_pull_request_event_includes_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    prd = (
        "# Spec\n\nUser model has `username` at app/models.py:2.\n"
        "See also docs/nothing.md:1.\n"
    )
    fake = _FakeGitHub(
        tarball=_make_tarball(_REPO_FILES),
        contents={"PROJECT_SPEC.md": prd},
        diff=_DIFF.encode("utf-8"),
    )
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = process_pull_request_event(_pr_payload(), client=_client())
    assert result.status == "completed"
    run = fake.check_runs[0]
    assert "text" in run["output"]
    assert "Drift findings" in run["output"]["text"]
    assert "Remediation" in run["output"]["text"]


def test_process_pull_request_event_no_prd_posts_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(tarball=_make_tarball(_REPO_FILES), contents={})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = process_pull_request_event(_pr_payload(), client=_client())
    assert result.status == "skipped"
    assert result.conclusion == "neutral"
    assert len(fake.check_runs) == 1
    assert fake.check_runs[0]["conclusion"] == "neutral"
    assert "no PRD" in fake.check_runs[0]["output"]["title"]


def test_process_pull_request_event_missing_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    payload = _pr_payload()
    payload["pull_request"] = {"head": {"ref": "feat"}}
    with pytest.raises(GitHubAutomationError, match="head.sha"):
        process_pull_request_event(payload, client=_client())


def test_process_pull_request_event_bad_tarball(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(tarball=b"not-a-tarball", contents={})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(GitHubAutomationError, match="tarball"):
        process_pull_request_event(_pr_payload(), client=_client())


def test_run_pull_request_automation_swallows_and_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(tarball=b"not-a-tarball", contents={})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = run_pull_request_automation(_pr_payload(), client=_client())
    assert result.status == "failed"
    assert result.conclusion == "neutral"
    assert len(fake.check_runs) == 1
    assert "automation error" in fake.check_runs[0]["output"]["title"]


def test_run_pull_request_automation_bad_payload() -> None:
    result = run_pull_request_automation(
        {"action": "opened"}, client=_client()
    )
    assert result.status == "failed"
    assert "missing" in result.message


def test_webhook_queues_automation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubAuth:
        def installation_token(
            self, installation_id: int
        ) -> GitHubInstallationToken:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token="ghs_x",
                expires_at="2027-01-01T00:00:00Z",
            )

    recorded: list[dict[str, Any]] = []

    def _fake_runner(payload: dict[str, Any], **kwargs: Any) -> None:
        recorded.append(payload)

    monkeypatch.setattr(
        server_module, "run_pull_request_automation", _fake_runner
    )
    app = create_app(
        webhook_secret=_SECRET, github_app=_StubAuth()  # type: ignore[arg-type]
    )
    body = json.dumps(_pr_payload()).encode("utf-8")
    resp = TestClient(app).post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, _SECRET),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "deliv-queue-1",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["automation"] == "queued"
    assert len(recorded) == 1
    assert recorded[0]["number"] == 5


def test_webhook_ignores_non_automation_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubAuth:
        def installation_token(
            self, installation_id: int
        ) -> GitHubInstallationToken:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token="ghs_x",
                expires_at="2027-01-01T00:00:00Z",
            )

    called: list[dict[str, Any]] = []
    monkeypatch.setattr(
        server_module,
        "run_pull_request_automation",
        lambda payload, **kwargs: called.append(payload),
    )
    app = create_app(
        webhook_secret=_SECRET, github_app=_StubAuth()  # type: ignore[arg-type]
    )
    body = json.dumps(_pr_payload(action="closed")).encode("utf-8")
    resp = TestClient(app).post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, _SECRET),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "deliv-skip-1",
        },
    )
    assert resp.status_code == 200
    assert "automation" not in resp.json()
    assert not called


def test_webhook_no_automation_without_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in (
        "PMCURSOR_GITHUB_APP_ID",
        "PMCURSOR_GITHUB_APP_PRIVATE_KEY",
        "PMCURSOR_GITHUB_APP_PRIVATE_KEY_PATH",
    ):
        monkeypatch.delenv(var, raising=False)
    called: list[dict[str, Any]] = []
    monkeypatch.setattr(
        server_module,
        "run_pull_request_automation",
        lambda payload, **kwargs: called.append(payload),
    )
    app = create_app(webhook_secret=_SECRET)
    body = json.dumps(_pr_payload()).encode("utf-8")
    resp = TestClient(app).post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, _SECRET),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "deliv-skip-2",
        },
    )
    assert resp.status_code == 200
    assert "automation" not in resp.json()
    assert not called


def test_webhook_auto_run_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubAuth:
        def installation_token(
            self, installation_id: int
        ) -> GitHubInstallationToken:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token="ghs_x",
                expires_at="2027-01-01T00:00:00Z",
            )

    called: list[dict[str, Any]] = []
    monkeypatch.setattr(
        server_module,
        "run_pull_request_automation",
        lambda payload, **kwargs: called.append(payload),
    )
    app = create_app(
        webhook_secret=_SECRET,
        github_app=_StubAuth(),  # type: ignore[arg-type]
        auto_run_pull_requests=False,
    )
    body = json.dumps(_pr_payload()).encode("utf-8")
    resp = TestClient(app).post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, _SECRET),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "deliv-skip-3",
        },
    )
    assert resp.status_code == 200
    assert "automation" not in resp.json()
    assert not called


def test_tarball_rejects_oversized_expansion(tmp_path: Path) -> None:
    tar_path = tmp_path / "bomb.tar.gz"
    tar_path.write_bytes(_make_tarball({"big.bin": "x" * 10_000}))
    with pytest.raises(GitHubAutomationError, match="expands beyond"):
        _extract_tarball(
            tar_path, tmp_path / "out", max_extracted_bytes=1024
        )


def test_tarball_rejects_member_count_cap(tmp_path: Path) -> None:
    files = {f"f{i}.txt": "x" for i in range(10)}
    tar_path = tmp_path / "many.tar.gz"
    tar_path.write_bytes(_make_tarball(files))
    with pytest.raises(GitHubAutomationError, match="members"):
        _extract_tarball(tar_path, tmp_path / "out", max_members=5)


def test_tarball_rejects_path_traversal(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("../evil.py")
        raw = b"bad"
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    tar_path = tmp_path / "evil.tar.gz"
    tar_path.write_bytes(buf.getvalue())
    with pytest.raises(GitHubAutomationError, match="extracted"):
        _extract_tarball(tar_path, tmp_path / "out")


def _merge_group_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "checks_requested",
        "repository": {"full_name": "octo/repo"},
        "installation": {"id": 7},
        "merge_group": {
            "head_sha": "mghead123",
            "base_sha": "mgbase456",
            "head_ref": "refs/heads/gh-readonly-queue/main/pr-5-abc123",
        },
    }
    payload.update(overrides)
    return payload


def _rerequest_payload(
    check_name: str = "pmcursor-drift", **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "rerequested",
        "repository": {"full_name": "octo/repo"},
        "installation": {"id": 7},
        "check_run": {
            "name": check_name,
            "head_sha": "abc123def",
            "pull_requests": [
                {
                    "number": 5,
                    "base": {"sha": "def456abc"},
                    "head": {"sha": "abc123def"},
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


def _fake_with_prd(prd: str) -> _FakeGitHub:
    return _FakeGitHub(
        tarball=_make_tarball(_REPO_FILES),
        contents={"PROJECT_SPEC.md": prd},
        diff=_DIFF.encode("utf-8"),
    )


def test_failure_conclusion_posts_marker_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _fake_with_prd(_PRD_FABRICATED)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = process_pull_request_event(_pr_payload(), client=_client())
    assert result.status == "completed"
    assert result.conclusion == "failure"
    assert len(fake.created_comments) == 1
    body = fake.created_comments[0]["body"]
    assert body.startswith("<!-- pmcursor-drift -->")
    assert "Drift findings" in body


def test_failure_comment_updates_existing_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _FakeGitHub(
        tarball=_make_tarball(_REPO_FILES),
        contents={"PROJECT_SPEC.md": _PRD_FABRICATED},
        diff=_DIFF.encode("utf-8"),
        comments=[{"id": 42, "body": "<!-- pmcursor-drift -->\nold run"}],
    )
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = process_pull_request_event(_pr_payload(), client=_client())
    assert result.conclusion == "failure"
    assert fake.created_comments == []
    assert len(fake.updated_comments) == 1
    comment_id, body = fake.updated_comments[0]
    assert comment_id == 42
    assert body["body"].startswith("<!-- pmcursor-drift -->")


def test_failure_comment_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _fake_with_prd(_PRD_FABRICATED)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = process_pull_request_event(
        _pr_payload(), client=_client(), post_failure_comment=False
    )
    assert result.conclusion == "failure"
    assert fake.created_comments == []


def test_merge_group_event_runs_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _fake_with_prd(_PRD)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = run_pull_request_automation(
        _merge_group_payload(), client=_client()
    )
    assert result is not None
    assert result.status == "completed"
    assert result.pr_number == 5
    assert len(fake.check_runs) == 1
    assert fake.check_runs[0]["head_sha"] == "mghead123"


def test_merge_group_failure_posts_comment_to_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _fake_with_prd(_PRD_FABRICATED)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = run_pull_request_automation(
        _merge_group_payload(), client=_client()
    )
    assert result is not None
    assert result.conclusion == "failure"
    assert len(fake.created_comments) == 1
    assert "/issues/5/comments" in "\n".join(fake.urls)


def test_merge_group_missing_head_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_jwt(monkeypatch)
    payload = _merge_group_payload()
    payload["merge_group"] = {"base_sha": "x"}
    result = run_pull_request_automation(payload, client=_client())
    assert result is not None
    assert result.status == "failed"
    assert "head_sha" in result.message


def test_check_run_rerequest_reruns_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _fake_with_prd(_PRD)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = run_pull_request_automation(
        _rerequest_payload(), client=_client()
    )
    assert result is not None
    assert result.status == "completed"
    assert result.pr_number == 5
    assert len(fake.check_runs) == 1
    assert "/compare/def456abc...abc123def" in "\n".join(fake.urls)


def test_check_run_rerequest_foreign_name_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_jwt(monkeypatch)
    fake = _fake_with_prd(_PRD)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    result = run_pull_request_automation(
        _rerequest_payload(check_name="other-check"), client=_client()
    )
    assert result is None
    assert fake.check_runs == []


def test_webhook_queues_merge_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubAuth:
        def installation_token(
            self, installation_id: int
        ) -> GitHubInstallationToken:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token="ghs_x",
                expires_at="2027-01-01T00:00:00Z",
            )

    recorded: list[dict[str, Any]] = []

    def _fake_runner(payload: dict[str, Any], **kwargs: Any) -> None:
        recorded.append(payload)

    monkeypatch.setattr(
        server_module, "run_pull_request_automation", _fake_runner
    )
    app = create_app(
        webhook_secret=_SECRET, github_app=_StubAuth()  # type: ignore[arg-type]
    )
    body = json.dumps(_merge_group_payload()).encode("utf-8")
    resp = TestClient(app).post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, _SECRET),
            "X-GitHub-Event": "merge_group",
            "X-GitHub-Delivery": "deliv-mq-1",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["automation"] == "queued"
    assert len(recorded) == 1


def test_webhook_queues_check_run_rerequest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubAuth:
        def installation_token(
            self, installation_id: int
        ) -> GitHubInstallationToken:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token="ghs_x",
                expires_at="2027-01-01T00:00:00Z",
            )

    recorded: list[dict[str, Any]] = []

    def _fake_runner(payload: dict[str, Any], **kwargs: Any) -> None:
        recorded.append(payload)

    monkeypatch.setattr(
        server_module, "run_pull_request_automation", _fake_runner
    )
    app = create_app(
        webhook_secret=_SECRET, github_app=_StubAuth()  # type: ignore[arg-type]
    )
    body = json.dumps(_rerequest_payload()).encode("utf-8")
    resp = TestClient(app).post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, _SECRET),
            "X-GitHub-Event": "check_run",
            "X-GitHub-Delivery": "deliv-rerun-1",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["automation"] == "queued"
    assert len(recorded) == 1


def test_webhook_skips_foreign_check_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubAuth:
        def installation_token(
            self, installation_id: int
        ) -> GitHubInstallationToken:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token="ghs_x",
                expires_at="2027-01-01T00:00:00Z",
            )

    called: list[dict[str, Any]] = []
    monkeypatch.setattr(
        server_module,
        "run_pull_request_automation",
        lambda payload, **kwargs: called.append(payload),
    )
    app = create_app(
        webhook_secret=_SECRET, github_app=_StubAuth()  # type: ignore[arg-type]
    )
    body = json.dumps(_rerequest_payload(check_name="eslint")).encode("utf-8")
    resp = TestClient(app).post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, _SECRET),
            "X-GitHub-Event": "check_run",
            "X-GitHub-Delivery": "deliv-rerun-2",
        },
    )
    assert resp.status_code == 200
    assert "automation" not in resp.json()
    assert not called


def test_webhook_passes_comment_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubAuth:
        def installation_token(
            self, installation_id: int
        ) -> GitHubInstallationToken:
            return GitHubInstallationToken(
                installation_id=installation_id,
                token="ghs_x",
                expires_at="2027-01-01T00:00:00Z",
            )

    recorded_kwargs: list[dict[str, Any]] = []

    def _fake_runner(payload: dict[str, Any], **kwargs: Any) -> None:
        recorded_kwargs.append(kwargs)

    monkeypatch.setattr(
        server_module, "run_pull_request_automation", _fake_runner
    )
    app = create_app(
        webhook_secret=_SECRET,
        github_app=_StubAuth(),  # type: ignore[arg-type]
        pr_failure_comments=False,
    )
    body = json.dumps(_pr_payload()).encode("utf-8")
    resp = TestClient(app).post(
        "/v1/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, _SECRET),
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "deliv-flag-1",
        },
    )
    assert resp.status_code == 200
    assert recorded_kwargs[0]["post_failure_comment"] is False
