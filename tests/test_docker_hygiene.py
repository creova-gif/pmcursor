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


def test_env_example_hygiene() -> None:
    env_example = REPO_ROOT / ".env.example"
    assert env_example.is_file(), ".env.example must exist at repository root"

    entries: dict[str, str] = {}
    for raw_line in env_example.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assert "=" in line, f"Invalid .env.example line: {raw_line}"
        key, value = line.split("=", 1)
        entries[key.strip()] = value.strip()

    secret_keys = (
        "PMCURSOR_API_TOKEN",
        "PMCURSOR_WEBHOOK_SECRET",
        "PMCURSOR_LINEAR_WEBHOOK_SECRET",
        "PMCURSOR_JIRA_WEBHOOK_SECRET",
    )
    for key in secret_keys:
        assert key in entries, f".env.example must define {key}"
        assert entries[key] == "", f".env.example secret key {key} must have an empty value"

    expected_defaults = {
        "PMCURSOR_RATE_LIMIT_PER_MIN": "120",
        "PMCURSOR_TRUST_PROXY": "false",
        "PMCURSOR_CORS_ORIGINS": "",
        "WEB_CONCURRENCY": "1",
    }
    for key, expected_value in expected_defaults.items():
        assert key in entries, f".env.example must define {key}"
        assert entries[key] == expected_value, (
            f".env.example key {key} must default to {expected_value!r}, found {entries[key]!r}"
        )


def test_docker_compose_hygiene() -> None:
    compose_file = REPO_ROOT / "docker-compose.yml"
    assert compose_file.is_file(), "docker-compose.yml must exist at repository root"

    content = compose_file.read_text(encoding="utf-8")
    assert re.search(r"^\s*pmcursor\s*:", content, flags=re.MULTILINE), (
        "docker-compose.yml must define service pmcursor"
    )
    assert re.search(r"^\s*build\s*:\s*\.\s*$", content, flags=re.MULTILINE), (
        "docker-compose.yml must build from repository root (build: .)"
    )
    assert "8000:8000" in content, "docker-compose.yml must map port 8000:8000"
    assert ".:/workspace:ro" in content, (
        "docker-compose.yml must mount the workspace read-only (.:/workspace:ro)"
    )
    assert re.search(r"^\s*restart\s*:\s*unless-stopped\s*$", content, flags=re.MULTILINE), (
        "docker-compose.yml must set restart: unless-stopped"
    )
    assert re.search(r"^\s*healthcheck\s*:", content, flags=re.MULTILINE), (
        "docker-compose.yml must define a healthcheck"
    )
    assert "http://127.0.0.1:8000/health" in content, (
        "docker-compose.yml healthcheck must probe http://127.0.0.1:8000/health"
    )
