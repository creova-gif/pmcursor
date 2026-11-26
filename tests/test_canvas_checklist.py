from __future__ import annotations

from pmcursor.checklists import EdgeCaseChecklist, EdgeCaseItem
from pmcursor.models import (
    DriftReport,
    RepoMap,
    SpecAlignmentScore,
)
from web.canvas import render_split_pane_canvas


def _make_sample_repo_and_report() -> tuple[RepoMap, DriftReport]:
    repo_map = RepoMap(repo_root="/tmp/sample-repo")
    report = DriftReport(
        prd_path="PROJECT_SPEC.md",
        status="DONE",
        alignment_score=SpecAlignmentScore(
            deterministic_score=100,
            workflow_score=100,
            overall_score=100,
            has_acceptance_cards=True,
            has_rollback_section=True,
            has_out_of_scope_section=True,
            has_adr_references=True,
        ),
        total_spec_contracts=0,
        matched_contracts=0,
        total_citations_checked=0,
        fabricated_citations_count=0,
        findings=[],
    )
    return repo_map, report


def test_canvas_without_checklist_renders_cleanly() -> None:
    repo_map, report = _make_sample_repo_and_report()
    html_doc = render_split_pane_canvas("# Sample PRD\n", repo_map, report, checklist=None)

    assert "<!DOCTYPE html>" in html_doc
    assert "Codebase Contracts" in html_doc
    assert "QA Edge-Case Checklist" not in html_doc


def test_canvas_with_checklist_renders_and_escapes_xss() -> None:
    repo_map, report = _make_sample_repo_and_report()
    xss_payload = "<script>alert(1)</script>"
    checklist = EdgeCaseChecklist(
        repo_root="/tmp/sample-repo",
        total_items=2,
        p0_count=1,
        items=[
            EdgeCaseItem(
                priority="P0",
                category="schema_validation",
                contract_name=f"UserCreate {xss_payload}",
                citation=f"src/models.py:12 {xss_payload}",
                scenario=f"Submit invalid payload {xss_payload}",
                expected_behavior=f"Return 422 error {xss_payload}",
            ),
            EdgeCaseItem(
                priority="P1",
                category="api_auth_error",
                contract_name="POST /v1/users",
                citation="src/routes.py:24",
                scenario="Unauthenticated request",
                expected_behavior="Return 401 Unauthorized",
            ),
        ],
        markdown="# Checklist",
    )

    html_doc = render_split_pane_canvas("# Sample PRD\n", repo_map, report, checklist=checklist)

    assert "QA Edge-Case Checklist" in html_doc
    assert "Total: 2 · P0: 1" in html_doc
    assert "[P0]" in html_doc
    assert "[P1]" in html_doc
    assert "schema_validation" in html_doc
    assert "api_auth_error" in html_doc
    assert "POST /v1/users" in html_doc
    assert "src/routes.py:24" in html_doc
    assert "Unauthenticated request" in html_doc
    assert "Return 401 Unauthorized" in html_doc

    assert xss_payload not in html_doc
    escaped_payload = "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert escaped_payload in html_doc
