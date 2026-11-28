"""Repository governance tests for CODEOWNERS, Dependabot, and security workflow."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CODEOWNERS_PATH = REPO_ROOT / ".github" / "CODEOWNERS"
DEPENDABOT_PATH = REPO_ROOT / ".github" / "dependabot.yml"
SECURITY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "security.yml"


def _read_non_empty(path: Path) -> str:
    assert path.is_file(), f"Missing governance file: {path}"
    content = path.read_text(encoding="utf-8")
    assert content.strip(), f"Governance file is empty: {path}"
    return content


def test_codeowners_exists_and_defines_expected_owners() -> None:
    content = _read_non_empty(CODEOWNERS_PATH)
    expected_rules = (
        "* @creova-gif",
        "/api/ @creova-gif",
        "/src/pmcursor/ @creova-gif",
        "/.github/ @creova-gif",
        "/SECURITY.md @creova-gif",
    )
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for rule in expected_rules:
        assert rule in lines, f"Missing CODEOWNERS rule: {rule}"


def test_dependabot_config_has_weekly_pip_and_github_actions() -> None:
    content = _read_non_empty(DEPENDABOT_PATH)
    assert re.search(r"^version:\s*2\s*$", content, re.MULTILINE)
    assert re.search(r"^updates:\s*$", content, re.MULTILINE)
    assert re.search(r'package-ecosystem:\s*["\']?pip["\']?', content)
    assert re.search(r'package-ecosystem:\s*["\']?github-actions["\']?', content)
    assert len(re.findall(r'interval:\s*["\']?weekly["\']?', content)) >= 2


def test_security_workflow_has_expected_triggers_and_scanners() -> None:
    content = _read_non_empty(SECURITY_WORKFLOW_PATH)
    assert re.search(r"^on:\s*$", content, re.MULTILINE)
    assert re.search(r"^\s+push:\s*$", content, re.MULTILINE)
    assert re.search(r"branches:\s*\[main\]", content)
    assert re.search(r"^\s+pull_request:\s*$", content, re.MULTILINE)
    assert re.search(r"^\s+schedule:\s*$", content, re.MULTILINE)
    assert 'cron: "0 6 * * 1"' in content

    assert re.search(r"^\s+security-scan:\s*$", content, re.MULTILINE)
    assert "runs-on: ubuntu-latest" in content
    assert "contents: read" in content
    assert re.search(r"actions/checkout@[0-9a-f]{40} # v\d+", content)
    assert "fetch-depth: 0" in content
    assert re.search(r"gitleaks/gitleaks-action@[0-9a-f]{40} # v\d+", content)
    assert "${{ secrets.GITHUB_TOKEN }}" in content
    assert re.search(r"actions/setup-python@[0-9a-f]{40} # v\d+", content)
    assert 'python-version: "3.12"' in content
    assert "ruff check --select S src indexer api web" in content
    assert "pip-audit" in content
