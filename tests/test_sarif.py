from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmcursor.cli import main
from pmcursor.models import DriftFinding, DriftReport, SpecAlignmentScore
from pmcursor.sarif import SARIF_SCHEMA_URL, drift_report_to_sarif


def _make_alignment_score() -> SpecAlignmentScore:
    return SpecAlignmentScore(
        overall_score=80,
        deterministic_score=80,
        workflow_score=80,
        has_acceptance_cards=True,
        has_rollback_section=True,
        has_out_of_scope_section=True,
        has_adr_references=True,
    )


def test_drift_report_to_sarif_with_findings() -> None:
    report = DriftReport(
        prd_path="docs/PRD.md",
        status="DONE_WITH_CONCERNS",
        alignment_score=_make_alignment_score(),
        total_spec_contracts=4,
        matched_contracts=2,
        total_citations_checked=3,
        fabricated_citations_count=1,
        findings=[
            DriftFinding(
                category="fabricated_citation",
                severity="critical",
                spec_reference="docs/PRD.md:10",
                code_citation="src/app/missing.py:42",
                message="Cited file does not exist.",
                remediation="Update citation to a valid file.",
            ),
            DriftFinding(
                category="type_mismatch",
                severity="high",
                spec_reference="User.age",
                code_citation="src/app/models.py:15",
                message="Field type mismatch.",
                remediation="Update field type in PRD.",
            ),
            DriftFinding(
                category="missing_telemetry",
                severity="medium",
                spec_reference="signup_completed",
                code_citation=None,
                message="Telemetry event not found in repo.",
                remediation="Instrument signup_completed event.",
            ),
            DriftFinding(
                category="unindexed_adr",
                severity="low",
                spec_reference="ADR-005",
                code_citation="docs/adr/005.md",
                message="ADR not indexed.",
                remediation="Add ADR header.",
            ),
            DriftFinding(
                category="type_mismatch",
                severity="high",
                spec_reference="User.email",
                code_citation="src/app/models.py:20",
                message="Another type mismatch.",
                remediation="Update email type in PRD.",
            ),
        ],
    )

    sarif = drift_report_to_sarif(report)

    assert sarif["$schema"] == SARIF_SCHEMA_URL
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1

    run = sarif["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "PMCursor"
    assert driver["informationUri"] == "https://github.com/creova-gif/pmcursor"
    assert driver["version"] == "0.1.0"

    rule_ids = [rule["id"] for rule in driver["rules"]]
    assert rule_ids == [
        "fabricated_citation",
        "missing_telemetry",
        "type_mismatch",
        "unindexed_adr",
    ]

    results = run["results"]
    assert len(results) == 5

    assert results[0]["ruleId"] == "fabricated_citation"
    assert results[0]["level"] == "error"
    assert results[0]["locations"][0]["physicalLocation"] == {
        "artifactLocation": {"uri": "src/app/missing.py"},
        "region": {"startLine": 42},
    }

    assert results[1]["level"] == "error"
    assert results[1]["locations"][0]["physicalLocation"] == {
        "artifactLocation": {"uri": "src/app/models.py"},
        "region": {"startLine": 15},
    }

    assert results[2]["level"] == "warning"
    assert results[2]["locations"][0]["physicalLocation"] == {
        "artifactLocation": {"uri": "docs/PRD.md"},
    }

    assert results[3]["level"] == "note"
    assert results[3]["locations"][0]["physicalLocation"] == {
        "artifactLocation": {"uri": "docs/adr/005.md"},
    }


def test_drift_report_to_sarif_zero_findings() -> None:
    report = DriftReport(
        prd_path="PROJECT_SPEC.md",
        status="DONE",
        alignment_score=_make_alignment_score(),
        total_spec_contracts=2,
        matched_contracts=2,
        total_citations_checked=2,
        fabricated_citations_count=0,
        findings=[],
    )

    sarif = drift_report_to_sarif(report)

    assert sarif["$schema"] == SARIF_SCHEMA_URL
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["rules"] == []
    assert run["results"] == []


def test_cli_drift_sarif(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass Item(BaseModel):\n    id: int\n",
        encoding="utf-8",
    )
    prd = tmp_path / "PRD.md"
    prd.write_text(
        "# Spec\n\n- `Item.id`: `str`\n- Citation: `missing.py:12`\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "drift",
            "--prd",
            str(prd),
            "--repo",
            str(repo),
            "--sarif",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["version"] == "2.1.0"
    assert payload["$schema"] == SARIF_SCHEMA_URL
    assert payload["runs"][0]["tool"]["driver"]["name"] == "PMCursor"
    assert len(payload["runs"][0]["results"]) >= 1
