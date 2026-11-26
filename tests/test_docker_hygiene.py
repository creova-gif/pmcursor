"""Hygiene tests for containerization and deployment documentation."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_hygiene() -> None:
    dockerfile = REPO_ROOT / "Dockerfile"
    assert dockerfile.is_file(), "Dockerfile must exist at repository root"

    content = dockerfile.read_text(encoding="utf-8")
    assert "python:3.12-slim" in content, "Dockerfile must use python:3.12-slim"

    user_matches = re.findall(r"^\s*USER\s+(\S+)", content, flags=re.MULTILINE)
    assert user_matches, "Dockerfile must define a USER instruction"
    assert all(u != "root" and u != "0" for u in user_matches), (
        f"Dockerfile must run as a non-root user, found: {user_matches}"
    )

    assert re.search(r"^\s*HEALTHCHECK\s+", content, flags=re.MULTILINE), (
        "Dockerfile must define a HEALTHCHECK instruction"
    )
    assert re.search(r"^\s*EXPOSE\s+8000\b", content, flags=re.MULTILINE), (
        "Dockerfile must expose port 8000"
    )
    assert "api.server:app" in content, "Dockerfile must invoke api.server:app"


def test_dockerignore_excludes_dev_artifacts() -> None:
    dockerignore = REPO_ROOT / ".dockerignore"
    assert dockerignore.is_file(), ".dockerignore must exist at repository root"

    entries = {
        line.strip()
        for line in dockerignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for required in (".git", ".venv", ".pytest_cache", "tests/"):
        assert required in entries, f".dockerignore must exclude {required}"


def test_deployment_docs_cover_required_topics() -> None:
    deployment_doc = REPO_ROOT / "docs" / "DEPLOYMENT.md"
    assert deployment_doc.is_file(), "docs/DEPLOYMENT.md must exist"

    content = deployment_doc.read_text(encoding="utf-8")
    for token in (
        "/health",
        "/readyz",
        "PMCURSOR_API_TOKEN",
        "WEB_CONCURRENCY",
        "PMCURSOR_WEBHOOK_SECRET",
        "PMCURSOR_LINEAR_WEBHOOK_SECRET",
        "PMCURSOR_JIRA_WEBHOOK_SECRET",
        "2MB",
    ):
        assert token in content, f"docs/DEPLOYMENT.md must document {token}"
