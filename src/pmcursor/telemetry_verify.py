from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pmcursor.models import RepoMap, TelemetrySourceKind

TelemetryDriftStatus = Literal[
    "matched",
    "missing_in_samples",
    "missing_properties",
    "unindexed_event",
]


class ObservedTelemetryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_name: str
    properties: dict[str, Any] = Field(default_factory=dict)
    source_kind: TelemetrySourceKind | None = None


class TelemetryDriftItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_name: str
    citation: str
    status: TelemetryDriftStatus
    missing_properties: list[str] = Field(default_factory=list)
    extra_properties: list[str] = Field(default_factory=list)


class TelemetryVerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_code_events: int
    total_observed_events: int
    matched_events: int
    items: list[TelemetryDriftItem]
    markdown: str


def _format_markdown(
    total_code_events: int,
    total_observed_events: int,
    matched_events: int,
    items: Sequence[TelemetryDriftItem],
) -> str:
    lines = [
        "## Telemetry Sample Verification",
        "",
        f"- Code events: {total_code_events}",
        f"- Observed events: {total_observed_events}",
        f"- Matched events: {matched_events}",
    ]
    if not items:
        lines.append("- No telemetry events found.")
        return "\n".join(lines)

    lines.append("")
    lines.append("| Event | Status | Citation | Missing Props | Extra Props |")
    lines.append("| --- | --- | --- | --- | --- |")
    for item in items:
        missing = ", ".join(item.missing_properties) or "-"
        extra = ", ".join(item.extra_properties) or "-"
        lines.append(
            f"| `{item.event_name}` | `{item.status}` | `{item.citation}` | {missing} | {extra} |"
        )
    return "\n".join(lines)


def verify_telemetry_samples(
    repo_map: RepoMap,
    samples: Sequence[ObservedTelemetryEvent | dict[str, Any]],
) -> TelemetryVerificationReport:
    """Compare indexed TelemetryContract definitions against observed runtime samples."""
    observed_by_event: dict[str, set[str]] = {}
    for raw_sample in samples:
        sample = (
            raw_sample
            if isinstance(raw_sample, ObservedTelemetryEvent)
            else ObservedTelemetryEvent.model_validate(raw_sample)
        )
        props = observed_by_event.setdefault(sample.event_name, set())
        props.update(sample.properties.keys())

    items: list[TelemetryDriftItem] = []
    matched_events = 0
    code_event_names: set[str] = set()

    for contract in repo_map.telemetry:
        code_event_names.add(contract.event_name)
        observed_props = observed_by_event.get(contract.event_name)
        if observed_props is None:
            items.append(
                TelemetryDriftItem(
                    event_name=contract.event_name,
                    citation=contract.citation,
                    status="missing_in_samples",
                    missing_properties=list(contract.properties),
                    extra_properties=[],
                )
            )
            continue

        expected_props = set(contract.properties)
        missing = sorted(expected_props - observed_props)
        extra = sorted(observed_props - expected_props)
        status: TelemetryDriftStatus = "missing_properties" if missing else "matched"
        if status == "matched":
            matched_events += 1
        items.append(
            TelemetryDriftItem(
                event_name=contract.event_name,
                citation=contract.citation,
                status=status,
                missing_properties=missing,
                extra_properties=extra,
            )
        )

    for event_name in sorted(observed_by_event):
        if event_name not in code_event_names:
            items.append(
                TelemetryDriftItem(
                    event_name=event_name,
                    citation="runtime:unindexed",
                    status="unindexed_event",
                    missing_properties=[],
                    extra_properties=sorted(observed_by_event[event_name]),
                )
            )

    total_code_events = len(repo_map.telemetry)
    total_observed_events = len(observed_by_event)
    markdown = _format_markdown(
        total_code_events=total_code_events,
        total_observed_events=total_observed_events,
        matched_events=matched_events,
        items=items,
    )
    return TelemetryVerificationReport(
        total_code_events=total_code_events,
        total_observed_events=total_observed_events,
        matched_events=matched_events,
        items=items,
        markdown=markdown,
    )
