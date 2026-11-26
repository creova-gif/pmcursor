from __future__ import annotations

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


def test_canvas_responsive_media_query_rules() -> None:
    repo_map, report = _make_sample_repo_and_report()
    html_doc = render_split_pane_canvas("# Sample PRD\n", repo_map, report)

    assert "@media (max-width: 900px)" in html_doc
    media_block = html_doc.split("@media (max-width: 900px)", maxsplit=1)[1].split(
        ".pane-heading", maxsplit=1
    )[0]
    assert "grid-template-columns: 1fr;" in media_block
    assert "padding: 16px;" in media_block
    assert ".canvas-header" in media_block
    assert "flex-direction: column;" in media_block


def test_canvas_clear_filter_button_and_script() -> None:
    repo_map, report = _make_sample_repo_and_report()
    html_doc = render_split_pane_canvas("# Sample PRD\n", repo_map, report)

    assert (
        '<button id="contract-search-clear" class="search-clear" type="button" '
        'aria-label="Clear contract filter" hidden>Clear</button>'
    ) in html_doc
    assert ".search-clear:focus-visible" in html_doc
    assert 'getElementById("contract-search-clear")' in html_doc
    assert 'event.key === "Escape"' in html_doc
    assert "clearFilter()" in html_doc
    assert "applyFilter();" in html_doc
    assert "input.focus();" in html_doc
