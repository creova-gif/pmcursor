from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmcursor.cli import main

_SECRET_ENV_VARS = (
    "PMCURSOR_API_TOKEN",
    "PMCURSOR_WEBHOOK_SECRET",
    "PMCURSOR_LINEAR_WEBHOOK_SECRET",
    "PMCURSOR_JIRA_WEBHOOK_SECRET",
)


def test_doctor_json_valid_repo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for var in _SECRET_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    exit_code = main(["doctor", "--repo", ".", "--json"])
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload["python_version"], str)
    assert payload["python_version"]
    assert isinstance(payload["server_extra_available"], bool)
    assert payload["plugin_valid"] is True
    assert payload["api_token_configured"] is False
    assert payload["github_webhook_secret_configured"] is False
    assert payload["linear_webhook_secret_configured"] is False
    assert payload["jira_webhook_secret_configured"] is False


def test_doctor_human_readable_never_leaks_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_values = {
        "PMCURSOR_API_TOKEN": "tok-super-secret-value-123",
        "PMCURSOR_WEBHOOK_SECRET": "gh-super-secret-value-456",
        "PMCURSOR_LINEAR_WEBHOOK_SECRET": "lin-super-secret-value-789",
        "PMCURSOR_JIRA_WEBHOOK_SECRET": "jira-super-secret-value-000",
    }
    for key, val in secret_values.items():
        monkeypatch.setenv(key, val)

    exit_code = main(["doctor", "--repo", "."])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "PMCursor Doctor" in captured.out
    assert "api_token_configured" in captured.out
    assert "configured" in captured.out
    for val in secret_values.values():
        assert val not in captured.out
        assert val not in captured.err


def test_doctor_json_never_leaks_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_values = {
        "PMCURSOR_API_TOKEN": "tok-json-secret-111",
        "PMCURSOR_WEBHOOK_SECRET": "gh-json-secret-222",
        "PMCURSOR_LINEAR_WEBHOOK_SECRET": "lin-json-secret-333",
        "PMCURSOR_JIRA_WEBHOOK_SECRET": "jira-json-secret-444",
    }
    for key, val in secret_values.items():
        monkeypatch.setenv(key, val)

    exit_code = main(["doctor", "--repo", ".", "--json"])
    assert exit_code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["api_token_configured"] is True
    assert payload["github_webhook_secret_configured"] is True
    assert payload["linear_webhook_secret_configured"] is True
    assert payload["jira_webhook_secret_configured"] is True
    for val in secret_values.values():
        assert val not in captured.out
        assert val not in captured.err


def test_doctor_missing_repo_returns_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "does-not-exist"
    exit_code = main(["doctor", "--repo", str(missing)])
    assert exit_code == 2
    assert "does not exist" in capsys.readouterr().err


def test_doctor_invalid_plugin_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["doctor", "--repo", str(tmp_path), "--json"])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["plugin_valid"] is False
