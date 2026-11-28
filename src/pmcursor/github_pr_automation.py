from __future__ import annotations

import base64
import json
import logging
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from api import compute_pr_impact
from pmcursor.github_app import GITHUB_API_BASE, GitHubAppAuth, GitHubAppError
from pmcursor.indexer import index_repository
from pmcursor.models import DriftReport
from pmcursor.publisher import _validate_outbound_url

logger = logging.getLogger(__name__)

_MAX_TARBALL_BYTES = 50 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 200 * 1024 * 1024
_MAX_TAR_MEMBERS = 50_000
_MAX_DIFF_BYTES = 1024 * 1024
_CHECK_RUN_SUMMARY_LIMIT = 60_000
_TARBALL_CHUNK = 64 * 1024
_FINDINGS_LIMIT = 25

PR_AUTOMATION_ACTIONS: frozenset[str] = frozenset(
    {"opened", "synchronize", "reopened", "ready_for_review"}
)
DEFAULT_PRD_CANDIDATES: tuple[str, ...] = (
    "PROJECT_SPEC.md",
    "PRD.md",
    "docs/PRD.md",
    ".pmcursor/prd.md",
)


class GitHubAutomationError(RuntimeError):
    """Raised when a pull-request automation step cannot be completed."""


class PullRequestAutomationResult(BaseModel):
    """Outcome of processing one pull_request webhook event."""

    model_config = ConfigDict(frozen=True)

    status: Literal["completed", "skipped", "failed"]
    conclusion: str
    repository: str
    pr_number: int
    head_sha: str
    installation_id: int
    findings_count: int = 0
    message: str


class GitHubRepoClient:
    """Installation-token-authenticated GitHub REST client for PR automation."""

    def __init__(
        self,
        *,
        auth: GitHubAppAuth,
        installation_id: int,
        api_base: str = GITHUB_API_BASE,
        timeout_seconds: float = 30.0,
        allow_private_urls: bool = False,
        max_tarball_bytes: int = _MAX_TARBALL_BYTES,
        max_diff_bytes: int = _MAX_DIFF_BYTES,
    ) -> None:
        self._auth = auth
        self._installation_id = installation_id
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._allow_private_urls = allow_private_urls
        self._max_tarball_bytes = max_tarball_bytes
        self._max_diff_bytes = max_diff_bytes

    def _open(
        self,
        url: str,
        *,
        accept: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> bytes:
        _validate_outbound_url(url, allow_private_urls=self._allow_private_urls)
        token = self._auth.installation_token(self._installation_id).token
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(  # noqa: S310 — URL validated above
            url, data=data, headers=headers, method=method
        )
        try:
            # URL scheme & SSRF safety verified above via _validate_outbound_url.
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=self._timeout_seconds
            ) as resp:
                return bytes(resp.read())
        except urllib.error.HTTPError as exc:
            raise GitHubAutomationError(
                f"GitHub API returned HTTP {exc.code} for {method} {url!r}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubAutomationError(
                f"GitHub API unreachable for {url!r}: {exc.reason}"
            ) from exc
        except GitHubAppError as exc:
            raise GitHubAutomationError(str(exc)) from exc

    def _stream_to_file(self, url: str, dest: Path) -> None:
        _validate_outbound_url(url, allow_private_urls=self._allow_private_urls)
        token = self._auth.installation_token(self._installation_id).token
        req = urllib.request.Request(  # noqa: S310 — URL validated above
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="GET",
        )
        written = 0
        try:
            # URL scheme & SSRF safety verified above via _validate_outbound_url.
            with (
                urllib.request.urlopen(  # noqa: S310
                    req, timeout=self._timeout_seconds
                ) as resp,
                dest.open("wb") as out,
            ):
                while chunk := resp.read(_TARBALL_CHUNK):
                    written += len(chunk)
                    if written > self._max_tarball_bytes:
                        raise GitHubAutomationError(
                            f"Repository tarball exceeds "
                            f"{self._max_tarball_bytes} bytes; refusing "
                            "to index"
                        )
                    out.write(chunk)
        except urllib.error.HTTPError as exc:
            raise GitHubAutomationError(
                f"GitHub API returned HTTP {exc.code} for {url!r}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubAutomationError(
                f"GitHub API unreachable for {url!r}: {exc.reason}"
            ) from exc

    def download_tarball(
        self, repo_full_name: str, ref: str, dest: Path
    ) -> None:
        """Stream the tarball of `ref` into `dest` (bounded)."""
        url = f"{self._api_base}/repos/{repo_full_name}/tarball/{ref}"
        self._stream_to_file(url, dest)

    def fetch_file(
        self, repo_full_name: str, path: str, ref: str
    ) -> str | None:
        """Return file contents at `ref`, or None when absent (404)."""
        url = f"{self._api_base}/repos/{repo_full_name}/contents/{path}?ref={ref}"
        try:
            raw = self._open(url, accept="application/vnd.github+json")
        except GitHubAutomationError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        content = payload.get("content")
        encoding = payload.get("encoding")
        if not isinstance(content, str):
            return None
        if encoding == "base64":
            try:
                return base64.b64decode(content).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise GitHubAutomationError(
                    f"Could not decode base64 content for {path!r}"
                ) from exc
        return content

    def fetch_compare_diff(
        self, repo_full_name: str, base_sha: str, head_sha: str
    ) -> str:
        """Return the base...head diff text, truncated at the configured cap.

        Pinned to immutable commits so a push landing mid-pipeline cannot
        swap in a diff that mismatches the indexed head tree.
        """
        url = (
            f"{self._api_base}/repos/{repo_full_name}"
            f"/compare/{base_sha}...{head_sha}"
        )
        raw = self._open(url, accept="application/vnd.github.diff")
        if len(raw) > self._max_diff_bytes:
            raw = raw[: self._max_diff_bytes]
            raw += b"\n# [pmcursor] diff truncated\n"
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitHubAutomationError("PR diff is not valid UTF-8") from exc

    def create_check_run(
        self,
        repo_full_name: str,
        *,
        head_sha: str,
        name: str,
        conclusion: str,
        title: str,
        summary: str,
        text: str = "",
    ) -> None:
        """Post a completed check run to the PR's head commit."""
        url = f"{self._api_base}/repos/{repo_full_name}/check-runs"
        output: dict[str, str] = {
            "title": title,
            "summary": summary[:_CHECK_RUN_SUMMARY_LIMIT],
        }
        if text:
            output["text"] = text[:_CHECK_RUN_SUMMARY_LIMIT]
        self._open(
            url,
            accept="application/vnd.github+json",
            method="POST",
            body={
                "name": name,
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": conclusion,
                "output": output,
            },
        )


def _extract_tarball(
    tarball_path: Path,
    dest_dir: Path,
    *,
    max_extracted_bytes: int = _MAX_EXTRACTED_BYTES,
    max_members: int = _MAX_TAR_MEMBERS,
) -> Path:
    """Extract a GitHub tarball safely; return the repo root inside.

    `filter="data"` bounds member paths and types; the cumulative size and
    member-count caps bound decompression, which the download cap cannot.
    """
    try:
        with tarfile.open(tarball_path, "r:gz") as tar:
            total_size = 0
            for count, member in enumerate(tar.getmembers(), start=1):
                if count > max_members:
                    raise GitHubAutomationError(
                        f"Repository tarball has more than {max_members} "
                        "members; refusing to extract"
                    )
                total_size += member.size
                if total_size > max_extracted_bytes:
                    raise GitHubAutomationError(
                        f"Repository tarball expands beyond "
                        f"{max_extracted_bytes} bytes; refusing to extract"
                    )
            tar.extractall(dest_dir, filter="data")
            roots = [m.name.split("/")[0] for m in tar.getmembers() if "/" in m.name]
    except tarfile.TarError as exc:
        raise GitHubAutomationError(
            f"Repository tarball could not be extracted: {exc}"
        ) from exc
    if not roots:
        raise GitHubAutomationError("Repository tarball is empty")
    root = dest_dir / roots[0]
    if not root.is_dir():
        raise GitHubAutomationError("Repository tarball has unexpected layout")
    return root


def _findings_text(report: DriftReport) -> str:
    """Render drift findings as markdown for the check-run `text` field."""
    if not report.findings:
        return ""
    lines = ["## Drift findings", ""]
    for finding in report.findings[:_FINDINGS_LIMIT]:
        ref = finding.code_citation or finding.spec_reference
        lines.append(
            f"- **{finding.severity}** `{finding.category}` "
            f"{finding.message} (`{ref}`)"
        )
        lines.append(f"  - Remediation: {finding.remediation}")
    if len(report.findings) > _FINDINGS_LIMIT:
        lines.append(
            f"- …and {len(report.findings) - _FINDINGS_LIMIT} more findings"
        )
    return "\n".join(lines)


def check_run_conclusion(report: DriftReport) -> str:
    """Map a deterministic DriftReport onto a GitHub check-run conclusion."""
    if report.fabricated_citations_count > 0 or report.status == "BLOCKED":
        return "failure"
    if any(f.severity == "critical" for f in report.findings):
        return "failure"
    if report.status == "DONE":
        return "success"
    return "neutral"


def process_pull_request_event(
    payload: dict[str, Any],
    *,
    client: GitHubRepoClient,
    prd_candidates: tuple[str, ...] = DEFAULT_PRD_CANDIDATES,
    check_run_name: str = "pmcursor-drift",
) -> PullRequestAutomationResult:
    """Index a PR head tree, run drift vs its PRD, post a check run."""
    repo_obj = payload.get("repository")
    pr_obj = payload.get("pull_request")
    install_obj = payload.get("installation")
    repo_name = repo_obj.get("full_name") if isinstance(repo_obj, dict) else None
    head_obj = pr_obj.get("head") if isinstance(pr_obj, dict) else None
    head_sha = head_obj.get("sha") if isinstance(head_obj, dict) else None
    base_obj = pr_obj.get("base") if isinstance(pr_obj, dict) else None
    base_sha = base_obj.get("sha") if isinstance(base_obj, dict) else None
    pr_number = payload.get("number")
    installation_id = (
        install_obj.get("id") if isinstance(install_obj, dict) else None
    )
    if not (isinstance(repo_name, str) and repo_name) or not isinstance(
        pr_number, int
    ):
        raise GitHubAutomationError(
            "pull_request payload missing repository.full_name or number"
        )
    if not (isinstance(head_sha, str) and head_sha):
        raise GitHubAutomationError("pull_request payload missing head.sha")
    if not (isinstance(base_sha, str) and base_sha):
        raise GitHubAutomationError("pull_request payload missing base.sha")
    if not isinstance(installation_id, int) or installation_id <= 0:
        raise GitHubAutomationError("pull_request payload missing installation.id")

    def _result(
        status: Literal["completed", "skipped", "failed"],
        conclusion: str,
        message: str,
        findings: int = 0,
    ) -> PullRequestAutomationResult:
        return PullRequestAutomationResult(
            status=status,
            conclusion=conclusion,
            repository=repo_name,
            pr_number=pr_number,
            head_sha=head_sha,
            installation_id=installation_id,
            findings_count=findings,
            message=message,
        )

    with tempfile.TemporaryDirectory(prefix="pmcursor-pr-") as tmp:
        tmp_dir = Path(tmp)
        tarball = tmp_dir / "repo.tar.gz"
        client.download_tarball(repo_name, head_sha, tarball)
        repo_root = _extract_tarball(tarball, tmp_dir / "tree")
        repo_map = index_repository(repo_root)

        prd_markdown: str | None = None
        prd_path = ""
        for candidate in prd_candidates:
            prd_markdown = client.fetch_file(repo_name, candidate, head_sha)
            if prd_markdown:
                prd_path = candidate
                break
        if not prd_markdown:
            tried = ", ".join(prd_candidates)
            client.create_check_run(
                repo_name,
                head_sha=head_sha,
                name=check_run_name,
                conclusion="neutral",
                title="PMCursor drift — no PRD found",
                summary=(
                    "No product spec found at any candidate path: "
                    f"{tried}. Add one to enable drift audits."
                ),
            )
            return _result(
                "skipped", "neutral", f"no PRD found at candidates: {tried}"
            )

        diff_text = client.fetch_compare_diff(repo_name, base_sha, head_sha)
        impact = compute_pr_impact(
            prd_markdown,
            diff_text,
            repo_map,
            prd_path=prd_path,
            org_id=repo_name,
        )
        conclusion = check_run_conclusion(impact.drift_report)
        findings = len(impact.drift_report.findings)
        client.create_check_run(
            repo_name,
            head_sha=head_sha,
            name=check_run_name,
            conclusion=conclusion,
            title=f"PMCursor drift — {impact.drift_report.status}",
            summary=impact.markdown_comment,
            text=_findings_text(impact.drift_report),
        )
        return _result(
            "completed",
            conclusion,
            f"{findings} findings across {len(repo_map.models)} models",
            findings=findings,
        )


def run_pull_request_automation(
    payload: dict[str, Any],
    *,
    client: GitHubRepoClient,
    check_run_name: str = "pmcursor-drift",
    prd_candidates: tuple[str, ...] = DEFAULT_PRD_CANDIDATES,
) -> PullRequestAutomationResult:
    """Best-effort wrapper: failures post a neutral check run, never raise."""
    try:
        return process_pull_request_event(
            payload,
            client=client,
            prd_candidates=prd_candidates,
            check_run_name=check_run_name,
        )
    except GitHubAutomationError as exc:
        logger.warning("pull_request automation failed: %s", exc)
        error = exc
    except Exception as exc:  # surfaced as a neutral check run
        logger.exception("pull_request automation crashed")
        error = GitHubAutomationError(f"automation crashed: {exc}")
    repo_obj = payload.get("repository")
    repo_name = repo_obj.get("full_name") if isinstance(repo_obj, dict) else ""
    pr_obj = payload.get("pull_request")
    head_obj = pr_obj.get("head") if isinstance(pr_obj, dict) else None
    head_sha = head_obj.get("sha") if isinstance(head_obj, dict) else ""
    install_obj = payload.get("installation")
    install_id = install_obj.get("id") if isinstance(install_obj, dict) else 0
    pr_number_raw = payload.get("number")
    pr_number = pr_number_raw if isinstance(pr_number_raw, int) else 0
    if isinstance(repo_name, str) and repo_name and head_sha:
        try:
            client.create_check_run(
                repo_name,
                head_sha=head_sha,
                name=check_run_name,
                conclusion="neutral",
                title="PMCursor drift — automation error",
                summary=f"The drift pipeline could not run: {error}",
            )
        except GitHubAutomationError:
            logger.warning("could not post neutral check run for %s", repo_name)
    return PullRequestAutomationResult(
        status="failed",
        conclusion="neutral",
        repository=repo_name if isinstance(repo_name, str) else "",
        pr_number=pr_number,
        head_sha=head_sha if isinstance(head_sha, str) else "",
        installation_id=install_id if isinstance(install_id, int) else 0,
        message=str(error),
    )


def build_repo_client(
    payload: dict[str, Any],
    *,
    github_app: GitHubAppAuth,
    api_base: str | None = None,
) -> GitHubRepoClient:
    """Build a GitHubRepoClient for the installation on a webhook payload."""
    install_obj = payload.get("installation")
    install_id = install_obj.get("id") if isinstance(install_obj, dict) else None
    if not isinstance(install_id, int) or install_id <= 0:
        raise GitHubAutomationError(
            "pull_request payload has no installation.id; cannot authenticate"
        )
    return GitHubRepoClient(
        auth=github_app,
        installation_id=install_id,
        api_base=api_base or GITHUB_API_BASE,
    )
