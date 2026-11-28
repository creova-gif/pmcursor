from __future__ import annotations

import logging
import os
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from pmcursor.models import CompletionStatus, DriftReport, SeverityLevel

logger = logging.getLogger(__name__)

LLMMethod = Literal["claude", "deterministic"]

ShipRecommendation = Literal["ship", "ship_with_notes", "hold"]

_SEVERITY_ORDER: dict[SeverityLevel, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

_SYSTEM_PROMPT = (
    "You are a senior product manager writing drift summaries for a PM audience. "
    "Ground every claim in the drift report provided. Never invent file paths, "
    "model names, or line numbers — cite only citations present in the input. "
    "Write concise Markdown: a headline, what changed, why it matters to the "
    "release, and what the PM should do next."
)


class PMDriftSummary(BaseModel):
    """PM-facing narrative summary of a DriftReport."""

    model_config = ConfigDict(frozen=True)

    prd_path: str
    method: LLMMethod
    ship_recommendation: ShipRecommendation
    headline: str
    narrative_markdown: str
    top_risks: list[str] = Field(default_factory=list)
    suggested_spec_edits: list[str] = Field(default_factory=list)
    drift_status: CompletionStatus
    alignment_score: int = Field(ge=0, le=100)


@runtime_checkable
class LLMClient(Protocol):
    """Minimal text-generation interface PMCursor LLM features consume."""

    def generate(self, *, system: str, prompt: str, max_tokens: int) -> str:
        """Return the model's text response for the given prompt."""
        ...


class LLMUnavailableError(RuntimeError):
    """Raised when a requested LLM backend is not usable."""


class AnthropicLLMClient:
    """LLMClient backed by the Anthropic SDK (`pmcursor[llm]` extra)."""

    def __init__(self, *, model: str = "claude-sonnet-4-6", api_key: str | None = None) -> None:
        try:
            import anthropic
        except ModuleNotFoundError as exc:
            raise LLMUnavailableError(
                "anthropic is required for Claude summaries. "
                "Install with: pip install 'pmcursor[llm]'"
            ) from exc
        resolved_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        if not resolved_key.strip():
            raise LLMUnavailableError(
                "ANTHROPIC_API_KEY is not set. Set it or use --offline for a "
                "deterministic summary."
            )
        self._client = anthropic.Anthropic(api_key=resolved_key)
        self._model = model

    def generate(self, *, system: str, prompt: str, max_tokens: int) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        )


def default_llm_client() -> LLMClient | None:
    """Return an AnthropicLLMClient when SDK and key are present, else None."""
    try:
        return AnthropicLLMClient()
    except LLMUnavailableError:
        return None


def _ship_recommendation(report: DriftReport) -> ShipRecommendation:
    blocking = any(
        f.severity in {"critical", "high"} for f in report.findings
    )
    if (
        blocking
        or report.fabricated_citations_count > 0
        or report.status == "BLOCKED"
    ):
        return "hold"
    if report.findings or report.status in {"DONE_WITH_CONCERNS", "NEEDS_CONTEXT"}:
        return "ship_with_notes"
    return "ship"


def _top_risks(report: DriftReport, *, limit: int = 3) -> list[str]:
    ordered = sorted(report.findings, key=lambda f: _SEVERITY_ORDER[f.severity])
    return [
        f"[{f.severity}] {f.category}: {f.message}"
        + (f" ({f.code_citation})" if f.code_citation else "")
        for f in ordered[:limit]
    ]


def _headline(report: DriftReport, ship: ShipRecommendation) -> str:
    label = {
        "ship": "Spec is aligned",
        "ship_with_notes": "Spec drifts in places",
        "hold": "Spec drift blocks release",
    }[ship]
    return f"{label} — {report.prd_path} scores {report.alignment_score.overall_score}/100"


def _deterministic_narrative(report: DriftReport, ship: ShipRecommendation) -> str:
    lines = [
        f"## {_headline(report, ship)}",
        "",
        f"- **Status:** `{report.status}`",
        (
            f"- **Findings:** {len(report.findings)} "
            f"({report.fabricated_citations_count} fabricated citations "
            f"of {report.total_citations_checked} checked)"
        ),
        f"- **Spec contracts matched:** {report.matched_contracts}/{report.total_spec_contracts}",
        "",
    ]
    if report.findings:
        lines.append("### Findings by severity")
        for finding in sorted(report.findings, key=lambda f: _SEVERITY_ORDER[f.severity]):
            citation = f" [`{finding.code_citation}`]" if finding.code_citation else ""
            lines.append(
                f"- **{finding.severity}** `{finding.category}` — "
                f"{finding.message}{citation} Fix: {finding.remediation}"
            )
    else:
        lines.append("No drift findings — the spec matches the indexed contracts.")
    return "\n".join(lines)


def _llm_prompt(report: DriftReport) -> str:
    findings = [
        {
            "category": f.category,
            "severity": f.severity,
            "spec_reference": f.spec_reference,
            "code_citation": f.code_citation,
            "message": f.message,
            "remediation": f.remediation,
        }
        for f in report.findings
    ]
    return (
        "Summarize this spec-drift report for a product manager.\n\n"
        f"prd_path: {report.prd_path}\n"
        f"status: {report.status}\n"
        f"alignment_score: {report.alignment_score.overall_score}/100\n"
        f"total_spec_contracts: {report.total_spec_contracts}\n"
        f"matched_contracts: {report.matched_contracts}\n"
        f"citations_checked: {report.total_citations_checked}\n"
        f"fabricated_citations: {report.fabricated_citations_count}\n"
        f"findings: {findings!r}\n"
    )


def summarize_drift_report(
    report: DriftReport,
    *,
    llm_client: LLMClient | None = None,
) -> PMDriftSummary:
    """Summarize a DriftReport for PMs. LLM narrates; gates stay deterministic.

    Ship recommendation, top risks, and suggested edits are always computed
    deterministically from the report. The narrative text uses Claude when a
    working LLMClient is supplied, and falls back to a template otherwise.
    """
    ship = _ship_recommendation(report)
    headline = _headline(report, ship)
    top_risks = _top_risks(report)
    suggested_edits = [
        f.remediation
        for f in sorted(report.findings, key=lambda x: _SEVERITY_ORDER[x.severity])
        if f.remediation
    ]

    method: LLMMethod = "deterministic"
    narrative = _deterministic_narrative(report, ship)
    if llm_client is not None:
        try:
            llm_text = llm_client.generate(
                system=_SYSTEM_PROMPT,
                prompt=_llm_prompt(report),
                max_tokens=1024,
            ).strip()
        except Exception as exc:  # noqa: BLE001 — any LLM failure degrades to template
            logger.warning("LLM summary failed, falling back to template: %s", exc)
        else:
            if llm_text:
                narrative = llm_text
                method = "claude"

    return PMDriftSummary(
        prd_path=report.prd_path,
        method=method,
        ship_recommendation=ship,
        headline=headline,
        narrative_markdown=narrative,
        top_risks=top_risks,
        suggested_spec_edits=suggested_edits,
        drift_status=report.status,
        alignment_score=report.alignment_score.overall_score,
    )
