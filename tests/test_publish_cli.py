from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmcursor.cli import main


def test_publish_cli_github_dry_run_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body_file = tmp_path / "comment.md"
    body_file.write_text("PR impact looks clean.", encoding="utf-8")

    code = main(
        [
            "publish",
            "--provider",
            "github",
            "--target",
            "acme/pmcursor#42",
            "--body-file",
            str(body_file),
            "--dry-run",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "github"
    assert payload["target_id"] == "acme/pmcursor#42"
    assert payload["dry_run"] is True
    assert payload["status_code"] == 0
    assert payload["url"] == "https://api.github.com/repos/acme/pmcursor/issues/42/comments"
    assert payload["body_preview"] == "PR impact looks clean."


def test_publish_cli_linear_dry_run_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body_file = tmp_path / "linear.md"
    body_file.write_text("Spec drift resolved.", encoding="utf-8")

    code = main(
        [
            "publish",
            "--provider",
            "linear",
            "--target",
            "ENG-101",
            "--body-file",
            str(body_file),
            "--dry-run",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "linear" in out
    assert "ENG-101" in out
    assert "dry-run" in out


def test_publish_cli_jira_dry_run_with_flag_and_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body_file = tmp_path / "jira.md"
    body_file.write_text("Ready for QA.", encoding="utf-8")

    code = main(
        [
            "publish",
            "--provider",
            "jira",
            "--target",
            "PM-7",
            "--jira-base-url",
            "https://jira.example.com",
            "--body-file",
            str(body_file),
            "--dry-run",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "jira"
    assert payload["target_id"] == "PM-7"
    assert payload["url"] == "https://jira.example.com/rest/api/2/issue/PM-7/comment"

    monkeypatch.setenv("PMCURSOR_JIRA_BASE_URL", "https://env-jira.example.com")
    code_env = main(
        [
            "publish",
            "--provider",
            "jira",
            "--target",
            "PM-8",
            "--body-file",
            str(body_file),
            "--dry-run",
            "--json",
        ]
    )
    assert code_env == 0
    payload_env = json.loads(capsys.readouterr().out)
    assert payload_env["url"] == "https://env-jira.example.com/rest/api/2/issue/PM-8/comment"


@pytest.mark.parametrize("bad_target", ["invalid", "owner/repo", "owner/repo#notint", "repo#12"])
def test_publish_cli_invalid_github_target_returns_2(
    tmp_path: Path, bad_target: str, capsys: pytest.CaptureFixture[str]
) -> None:
    body_file = tmp_path / "comment.md"
    body_file.write_text("hello", encoding="utf-8")

    code = main(
        [
            "publish",
            "--provider",
            "github",
            "--target",
            bad_target,
            "--body-file",
            str(body_file),
            "--dry-run",
        ]
    )

    assert code == 2
    assert "Error:" in capsys.readouterr().err


def test_publish_cli_missing_body_file_returns_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does_not_exist.md"

    code = main(
        [
            "publish",
            "--provider",
            "linear",
            "--target",
            "ENG-1",
            "--body-file",
            str(missing),
            "--dry-run",
        ]
    )

    assert code == 2
    assert "Error:" in capsys.readouterr().err


def test_publish_cli_missing_jira_base_url_returns_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("PMCURSOR_JIRA_BASE_URL", raising=False)
    body_file = tmp_path / "jira.md"
    body_file.write_text("hello", encoding="utf-8")

    code = main(
        [
            "publish",
            "--provider",
            "jira",
            "--target",
            "PM-9",
            "--body-file",
            str(body_file),
            "--dry-run",
        ]
    )

    assert code == 2
    assert "Error:" in capsys.readouterr().err
