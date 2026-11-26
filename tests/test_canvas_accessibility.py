from __future__ import annotations

from pmcursor.models import (
    DriftFinding,
    DriftReport,
    FieldContract,
    ModelContract,
    RepoMap,
    SpecAlignmentScore,
)
from web.canvas import render_split_pane_canvas


def _make_sample_repo_and_report() -> tuple[RepoMap, DriftReport]:
    repo_map = RepoMap(
        repo_root="/tmp/sample-repo",
        models=[
            ModelContract(
                name="UserCreate",
                file_path="src/models.py",
                line=10,
                base_classes=["BaseModel"],
                fields=[FieldContract(name="email", type_annotation="str", line=11)],
            )
        ],
    )
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
        total_spec_contracts=1,
        matched_contracts=1,
        total_citations_checked=1,
        fabricated_citations_count=0,
        findings=[
            DriftFinding(
                severity="low",
                category="missing_field",
                spec_reference="UserCreate.email",
                code_citation="src/models.py:10",
                message="Sample finding for table header accessibility check.",
                remediation="Add missing field to model.",
            )
        ],
    )
    return repo_map, report


def test_canvas_wcag_landmarks_and_skip_link() -> None:
    repo_map, report = _make_sample_repo_and_report()
    html_doc = render_split_pane_canvas("# Sample PRD\n", repo_map, report)

    assert '<html lang="en">' in html_doc
    assert ".skip-link" in html_doc
    assert '<a class="skip-link" href="#main-workspace">Skip to workspace</a>' in html_doc
    assert '<header class="canvas-header" role="banner">' in html_doc
    assert '<main id="main-workspace" class="split-workspace">' in html_doc
    assert '<section class="pane pane-left"' in html_doc
    assert 'aria-labelledby="prd-pane-heading"' in html_doc
    assert '<h2 id="prd-pane-heading" class="pane-heading">Living PRD</h2>' in html_doc
    assert '<aside class="pane pane-right"' in html_doc
    assert 'aria-labelledby="contracts-pane-heading"' in html_doc
    assert '<h2 id="contracts-pane-heading" class="pane-heading">Codebase Contracts</h2>' in html_doc


def test_canvas_wcag_focus_motion_table_and_aria() -> None:
    repo_map, report = _make_sample_repo_and_report()
    html_doc = render_split_pane_canvas("# Sample PRD\n", repo_map, report)

    assert ":focus-visible" in html_doc
    assert "outline: none;" not in html_doc
    assert "prefers-reduced-motion: reduce" in html_doc

    for col in ("Severity", "Category", "Spec Reference", "Code Citation", "Message"):
        assert f'<th scope="col">{col}</th>' in html_doc

    assert 'aria-label="Filter indexed contracts"' in html_doc
    assert 'aria-describedby="contract-filter-status"' in html_doc
    assert '<div id="contract-filter-status" class="contract-count" aria-live="polite">' in html_doc
    assert 'getElementById("contract-filter-status")' in html_doc

    assert '<span class="status-dot" aria-hidden="true"' in html_doc
    assert '<span class="search-kbd" aria-hidden="true">/</span>' in html_doc
