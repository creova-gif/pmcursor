from __future__ import annotations

from pathlib import Path

import pmcursor


def test_top_level_exports() -> None:
    expected_exports = [
        "audit_ticket_against_repo",
        "TicketSyncReport",
        "generate_edge_case_checklist",
        "EdgeCaseChecklist",
    ]
    for symbol in expected_exports:
        assert hasattr(pmcursor, symbol)
        assert symbol in pmcursor.__all__


def test_validate_plugin_manifests() -> None:
    result = pmcursor.validate_plugin_manifests(Path("."))
    assert result.valid is True
