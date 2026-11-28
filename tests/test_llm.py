from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from pmcursor.cli import main as cli_main
from pmcursor.llm import (
    AnthropicLLMClient,
    LLMUnavailableError,
    PMDriftSummary,
    default_llm_client,
    summarize_drift_report,
)
from pmcursor.models import (
    CompletionStatus,
    DriftFinding,
    DriftReport,
    SpecAlignmentScore,
)


def _score() -> SpecAlignmentScore:
    return SpecAlignmentScore(
        overall_score=80,
        deterministic_score=80,
        workflow_score=80,
        has_acceptance_cards=True,
        has_rollback_section=True,
        has_out_of_scope_section=True,
        has_adr_references=True,
    )


def _report(
    *,
    status: CompletionStatus = "DONE",
    findings: list[DriftFinding] | None = None,
    fabricated: int = 0,
) -> DriftReport:
    return DriftReport(
        prd_path="PRD.md",
        status=status,
        alignment_score=_score(),
        total_spec_contracts=3,
        matched_contracts=3,
        total_citations_checked=5,
        fabricated_citations_count=fabricated,
        findings=findings or [],
    )


def _finding(severity: str = "medium") -> DriftFinding:
    return DriftFinding(
        category="type_mismatch",
        severity=severity,  # type: ignore[arg-type]
        spec_reference="`Order.total_cents: str`",
        code_citation="app/models.py:5",
        message="Field type differs from spec",
        remediation="Update the spec to `int` or fix the model",
    )


class _StubClient:
    def __init__(self, text: str = "## Stub narrative") -> None:
        self._text = text
        self.calls: list[dict[str, object]] = []

    def generate(self, *, system: str, prompt: str, max_tokens: int) -> str:
        self.calls.append({"system": system, "prompt": prompt, "max_tokens": max_tokens})
        return self._text


class _FailingClient:
    def generate(self, *, system: str, prompt: str, max_tokens: int) -> str:
        raise RuntimeError("boom")


def _create_sample_repo(base: Path) -> Path:
    app_dir = base / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "models.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class Order(BaseModel):\n"
        "    order_id: str\n"
        "    total_cents: int\n",
        encoding="utf-8",
    )
    return base


def test_deterministic_summary_ship_on_clean_report() -> None:
    summary = summarize_drift_report(_report())
    assert summary.method == "deterministic"
    assert summary.ship_recommendation == "ship"
    assert summary.top_risks == []
    assert "scores 80/100" in summary.headline
    assert "No drift findings" in summary.narrative_markdown


def test_deterministic_summary_hold_on_critical_finding() -> None:
    summary = summarize_drift_report(
        _report(findings=[_finding("critical")], status="BLOCKED")
    )
    assert summary.ship_recommendation == "hold"
    assert summary.top_risks[0].startswith("[critical] type_mismatch")
    assert "app/models.py:5" in summary.top_risks[0]
    assert summary.suggested_spec_edits == [
        "Update the spec to `int` or fix the model"
    ]


def test_deterministic_summary_hold_on_fabricated_citations() -> None:
    summary = summarize_drift_report(_report(fabricated=2))
    assert summary.ship_recommendation == "hold"


def test_deterministic_summary_ship_with_notes_on_medium() -> None:
    summary = summarize_drift_report(
        _report(findings=[_finding("medium")], status="DONE_WITH_CONCERNS")
    )
    assert summary.ship_recommendation == "ship_with_notes"


def test_llm_client_narrates_but_gates_stay_deterministic() -> None:
    stub = _StubClient("## Claude narrative\n\nHold the release.")
    summary = summarize_drift_report(
        _report(findings=[_finding("high")]),
        llm_client=stub,
    )
    assert summary.method == "claude"
    assert summary.narrative_markdown == "## Claude narrative\n\nHold the release."
    # The gate is computed from the report, not from LLM prose.
    assert summary.ship_recommendation == "hold"
    assert stub.calls and stub.calls[0]["system"]


def test_failing_llm_client_falls_back_to_deterministic() -> None:
    summary = summarize_drift_report(_report(), llm_client=_FailingClient())
    assert summary.method == "deterministic"
    assert "No drift findings" in summary.narrative_markdown


def test_default_llm_client_none_without_sdk_or_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert default_llm_client() is None


def test_anthropic_client_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pytest.importorskip("anthropic")
    with pytest.raises(LLMUnavailableError, match="ANTHROPIC_API_KEY"):
        AnthropicLLMClient()


def test_cli_summarize_offline_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _create_sample_repo(tmp_path / "repo")
    prd = tmp_path / "PRD.md"
    prd.write_text("# Spec\n", encoding="utf-8")
    rc = cli_main(
        ["summarize", "--prd", str(prd), "--repo", str(repo), "--offline", "--json"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    summary = PMDriftSummary.model_validate(payload)
    assert summary.method == "deterministic"
    assert summary.prd_path.endswith("PRD.md")


def test_api_summarize_injects_llm_client(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path / "repo")
    stub = _StubClient()
    app = create_app(llm_client=stub)
    client = TestClient(app)
    resp = client.post(
        "/v1/summarize",
        json={
            "prd_markdown": "# Order PRD\n",
            "repo_root": str(repo),
            "prd_path": "PRD.md",
        },
    )
    assert resp.status_code == 200
    summary = PMDriftSummary.model_validate(resp.json())
    assert summary.method == "claude"
    assert stub.calls


def test_api_summarize_offline_stays_deterministic(tmp_path: Path) -> None:
    repo = _create_sample_repo(tmp_path / "repo")
    stub = _StubClient()
    app = create_app(llm_client=stub)
    client = TestClient(app)
    resp = client.post(
        "/v1/summarize",
        json={
            "prd_markdown": "# Order PRD\n",
            "repo_root": str(repo),
            "prd_path": "PRD.md",
            "offline": True,
        },
    )
    assert resp.status_code == 200
    summary = PMDriftSummary.model_validate(resp.json())
    assert summary.method == "deterministic"
    assert stub.calls == []
