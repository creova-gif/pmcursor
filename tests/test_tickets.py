from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.server import _is_authorized
from pmcursor.cli import main
from pmcursor.indexer import index_repository
from pmcursor.tickets import audit_ticket_against_repo


def _write_sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "models.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class TicketItem(BaseModel):\n"
        "    item_id: str\n"
        "    priority: int\n",
        encoding="utf-8",
    )
    return tmp_path


def test_audit_ticket_linear_and_jira(tmp_path: Path) -> None:
    repo_root = _write_sample_repo(tmp_path)
    repo_map = index_repository(repo_root)

    clean_description = (
        "Backed by `models.py:3`.\n"
        "- `TicketItem.item_id: str`\n"
        "- `TicketItem.priority: int`\n"
    )
    drifted_description = (
        "Backed by `models.py:3`.\n"
        "- `TicketItem.item_id: str`\n"
        "- `TicketItem.priority: str`\n"
    )

    linear_clean = audit_ticket_against_repo(
        "LIN-42",
        "Add ticket item",
        clean_description,
        repo_map,
        provider="linear",
        repo_root=repo_root,
    )
    assert linear_clean.ticket_id == "LIN-42"
    assert linear_clean.provider == "linear"
    assert linear_clean.drift_report.status == "DONE"
    assert linear_clean.drift_report.findings == []
    assert "linear:LIN-42" in linear_clean.comment_markdown

    jira_clean = audit_ticket_against_repo(
        "PM-101",
        "Add ticket item",
        clean_description,
        repo_map,
        provider="jira",
        repo_root=repo_root,
    )
    assert jira_clean.ticket_id == "PM-101"
    assert jira_clean.provider == "jira"
    assert jira_clean.drift_report.status == "DONE"
    assert jira_clean.drift_report.findings == []
    assert "jira:PM-101" in jira_clean.comment_markdown

    linear_drifted = audit_ticket_against_repo(
        "LIN-42",
        "Add ticket item",
        drifted_description,
        repo_map,
        provider="linear",
        repo_root=repo_root,
    )
    assert linear_drifted.drift_report.status == "DONE_WITH_CONCERNS"
    assert any(
        f.category == "type_mismatch" and "TicketItem.priority" in f.spec_reference
        for f in linear_drifted.drift_report.findings
    )

    jira_drifted = audit_ticket_against_repo(
        "PM-101",
        "Add ticket item",
        drifted_description,
        repo_map,
        provider="jira",
        repo_root=repo_root,
    )
    assert jira_drifted.drift_report.status == "DONE_WITH_CONCERNS"
    assert any(
        f.category == "type_mismatch" and "TicketItem.priority" in f.spec_reference
        for f in jira_drifted.drift_report.findings
    )


def test_cli_ticket_sync_json_and_fail_on_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = _write_sample_repo(tmp_path)
    clean_body = tmp_path / "clean_ticket.md"
    clean_body.write_text(
        "- `TicketItem.item_id: str`\n- `TicketItem.priority: int`\n",
        encoding="utf-8",
    )
    drifted_body = tmp_path / "drifted_ticket.md"
    drifted_body.write_text(
        "- `TicketItem.item_id: str`\n- `TicketItem.priority: str`\n",
        encoding="utf-8",
    )

    clean_exit = main(
        [
            "ticket-sync",
            "--id",
            "LIN-42",
            "--title",
            "Clean ticket",
            "--body-file",
            str(clean_body),
            "--provider",
            "linear",
            "--repo",
            str(repo_root),
            "--json",
            "--fail-on-drift",
        ]
    )
    assert clean_exit == 0
    clean_payload = json.loads(capsys.readouterr().out)
    assert clean_payload["ticket_id"] == "LIN-42"
    assert clean_payload["provider"] == "linear"
    assert clean_payload["drift_report"]["status"] == "DONE"
    assert clean_payload["drift_report"]["findings"] == []

    drifted_exit = main(
        [
            "ticket-sync",
            "--id",
            "PM-101",
            "--title",
            "Drifted ticket",
            "--body-file",
            str(drifted_body),
            "--provider",
            "jira",
            "--repo",
            str(repo_root),
            "--json",
            "--fail-on-drift",
        ]
    )
    assert drifted_exit == 1
    drifted_payload = json.loads(capsys.readouterr().out)
    assert drifted_payload["ticket_id"] == "PM-101"
    assert drifted_payload["provider"] == "jira"
    assert drifted_payload["drift_report"]["status"] == "DONE_WITH_CONCERNS"
    assert len(drifted_payload["drift_report"]["findings"]) >= 1


@pytest.mark.parametrize("token", ["token-à", "token-Å"])
def test_is_authorized_preserves_trailing_latin1_bytes_for_a_grave_and_a_ring(
    token: str,
) -> None:
    wire_latin1 = token.encode("utf-8").decode("latin-1")
    assert _is_authorized(token, f"Bearer {wire_latin1}", "") is True
    assert _is_authorized(token, "", wire_latin1) is True
    assert _is_authorized(token, f"Bearer {wire_latin1}x", "") is False
